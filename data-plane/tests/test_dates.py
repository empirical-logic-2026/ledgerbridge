"""Reliable dates (core/dates.py): TallyPrime in Educational mode gives correct balances on
the 1st, 2nd and 31st of a month only (the test company, 2026-10-15: a balance for the 30th
included later vouchers). Validation then runs as of the latest reliable date, and month
ends move to the next reliable one; year ends and statements use the 31st, or else the 2nd
(never the 1st: Tally's computed profit there disagrees with its ledgers, 2026-10-22). The
output shows the dates used."""

from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.orm import Session

from connectors.base import SourceBalances
from connectors.tally.connector import TallyConnector
from core.dates import EDUCATIONAL, EVERY_DAY, date_rule
from core.models import system as S  # noqa: N812
from tests.conftest import COMPANY
from tests.test_cli import run_cli  # noqa: F401, F811 - the fixture
from workers.validate import run_validation, source_controls


@pytest.mark.parametrize(
    ("asked", "as_of"),
    [
        (date(2026, 10, 15), date(2026, 10, 2)),
        (date(2026, 10, 2), date(2026, 10, 2)),
        (date(2026, 10, 1), date(2026, 10, 1)),
        (date(2026, 10, 31), date(2026, 10, 31)),
        (date(2026, 9, 30), date(2026, 9, 2)),
    ],
)
def test_as_of_moves_back_to_a_reliable_date(asked: date, as_of: date) -> None:
    assert EDUCATIONAL.on_or_before(asked) == as_of
    assert EVERY_DAY.on_or_before(asked) == asked


@pytest.mark.parametrize(
    ("end", "used"),
    [
        (date(2021, 3, 31), date(2021, 3, 31)),  # a 31 March year end stays
        (date(2026, 6, 30), date(2026, 7, 1)),  # a 30 June one moves to 1 July
        (date(2026, 2, 28), date(2026, 3, 1)),
        (date(2024, 2, 29), date(2024, 3, 1)),
        (date(2026, 4, 30), date(2026, 5, 1)),
    ],
)
def test_month_and_year_ends_move_forward_to_a_reliable_date(end: date, used: date) -> None:
    assert EDUCATIONAL.on_or_after(end) == used
    assert EVERY_DAY.on_or_after(end) == end


@pytest.mark.parametrize(
    ("end", "used"),
    [
        (date(2021, 3, 31), date(2021, 3, 31)),  # the 31st itself where it exists
        (date(2026, 6, 30), date(2026, 7, 2)),  # otherwise the 2nd, never the 1st
        (date(2026, 2, 28), date(2026, 3, 2)),
        (date(2024, 2, 29), date(2024, 3, 2)),
        (date(2026, 10, 2), date(2026, 10, 2)),
    ],
)
def test_period_ends_use_the_31st_or_the_2nd_never_the_1st(end: date, used: date) -> None:
    assert EDUCATIONAL.period_end(end) == used
    assert EVERY_DAY.period_end(end) == end


def test_the_connection_setting_decides_and_auto_asks_tally() -> None:
    def tally(answer: str) -> httpx.MockTransport:
        def respond(request: httpx.Request) -> httpx.Response:
            assert "$$LicenseInfo:IsEducationalMode" in request.content.decode()
            return httpx.Response(
                200,
                content=(
                    "<ENVELOPE><BODY><DATA><COLLECTION><COMPANY NAME='X'>"
                    f"{answer}</COMPANY></COLLECTION></DATA></BODY></ENVELOPE>"
                ).encode(),
            )

        return httpx.MockTransport(respond)

    entity = SimpleNamespace()
    config = {"url": "http://tally.test:9000"}
    yes = TallyConnector.from_config(config, transport=tally("<LBEDUCATIONAL>Yes</LBEDUCATIONAL>"))
    assert date_rule(yes, entity) is EDUCATIONAL
    no = TallyConnector.from_config(config, transport=tally("<LBEDUCATIONAL>No</LBEDUCATIONAL>"))
    assert date_rule(no, entity) is EVERY_DAY
    silent = TallyConnector.from_config(config, transport=tally(""))
    assert date_rule(silent, entity) is EVERY_DAY  # Tally doesn't say: as before
    forced = TallyConnector.from_config({**config, "educational": "yes"}, transport=tally(""))
    assert date_rule(forced, entity) is EDUCATIONAL


def test_validation_runs_as_of_the_latest_reliable_date(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    connector.educational = "yes"
    said: list[str] = []
    (report,) = run_validation(
        db, synced, connector, [COMPANY], as_of=date(2026, 10, 15), progress=said.append
    )
    assert report.as_of == date(2026, 10, 2)
    assert any(
        "validating as of 2026-10-02" in m and "instead of 2026-10-15" in m
        and "Educational mode" in m
        for m in said
    )  # fmt: skip


def test_a_30_june_year_end_is_checked_on_2_july() -> None:
    asked: list[date] = []

    class Source:
        def closing_balances(self, entity, as_of):  # noqa: ANN001, ANN202
            asked.append(as_of)
            return SourceBalances(as_of, {})

    row = SimpleNamespace(books_from=date(2024, 7, 1), fy_start_month=7)
    entity = SimpleNamespace(books_from=date(2024, 7, 1))
    said: list[str] = []
    controls = source_controls(
        Source(),
        entity,
        row,
        date(2026, 10, 2),
        EDUCATIONAL,
        said.append,  # type: ignore[arg-type]
    )
    assert sorted(controls.year_ends) == [date(2025, 7, 2), date(2026, 7, 2)]
    assert asked == [date(2025, 7, 2), date(2026, 7, 2)]
    assert "year end 2025-06-30 checked as of 2025-07-02" in said[0]
    controls = source_controls(Source(), entity, row, date(2026, 10, 2))  # type: ignore[arg-type]
    assert sorted(controls.year_ends) == [date(2025, 6, 30), date(2026, 6, 30)]


def test_connect_stores_the_setting(db: Session, run_cli) -> None:  # noqa: ANN001, F811
    code, out = run_cli("connect", "--connection", "tally-pilot", "--source", "tally",
                        "--origin", "backup", "--all", "--educational", "yes")  # fmt: skip
    assert code == 0, out
    assert "Educational mode: yes" in out
    connection = db.query(S.Connection).filter_by(name="tally-pilot").one()
    assert connection.config["educational"] == "yes"


def test_analyse_shows_the_dates_used() -> None:
    from workers.analyse import Analyser

    analyser = object.__new__(Analyser)
    analyser.rule = EDUCATIONAL
    analyser.as_of = date(2026, 10, 2)
    analyser.year_ends = [date(2025, 7, 2)]
    line = analyser._dates_used()
    assert line.startswith("Dates used: as of 2026-10-02; year ends 2025-07-02; Educational")
