"""Statements built from our books against the source's own (ADR-040; RPT-012, VAL-015), on
the test company's recordings of 2026-10-22: its books (stock_values/books) and its
statements with accounts integrated with inventory and without (stock_values/integrated,
stock_values/not_integrated)."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.tally.connector import TallyConnector
from connectors.tally.fixtures import FixtureTransport
from core import statements
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from tests.conftest import COMPANY
from tests.stock_replay import FOLDER, replay
from workers.extract import get_or_create_connection
from workers.sync import run_sync

AS_OF = date(2026, 10, 2)
DATES = (date(2026, 4, 1), date(2026, 5, 31), date(2026, 8, 31), AS_OF)


@pytest.fixture
def books(db: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[S.Connection]:
    """The test company's books as recorded on the day its statements were."""
    monkeypatch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )
    connection = get_or_create_connection(db, "tally-test", "tally")
    db.commit()
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=FixtureTransport(FOLDER / "books")
    )
    result = run_sync(db, connection, connector, [COMPANY])
    assert result.status == "succeeded" and result.failed == 0
    yield connection


def _source(case: str, as_of: date = AS_OF):  # noqa: ANN202
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000", "educational": "yes"}, transport=replay(case)
    )
    return connector.source_statements(connector.list_entities()[0], as_of)


@pytest.mark.parametrize("case", ["integrated", "not_integrated"])
@pytest.mark.parametrize("as_of", DATES)
def test_our_statements_match_the_sources_line_by_line(
    db: Session, books: S.Connection, case: str, as_of: date
) -> None:
    entity_id = db.scalars(select(A.Entity)).one().id
    result = statements.refresh(db, entity_id, books.id, "live", _source(case, as_of))
    listed = [(d.statement, d.key, str(d.ours), str(d.source)) for d in result.differences]
    assert listed == []
    assert result.compared > 15


@pytest.mark.parametrize(("case", "integrated"), [("integrated", True), ("not_integrated", False)])
def test_the_connector_reads_each_companys_integration_setting(case: str, integrated: bool) -> None:
    """ISINTEGRATED as the company record gives it (Yes, then No after it was switched
    off in TallyPrime's company features)."""
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=replay(case)
    )
    entity = connector.list_entities()[0]
    assert connector._integrated(entity) is integrated
    assert _source(case).integrated is integrated


def test_without_integration_the_stock_is_the_stock_ledgers() -> None:
    """Not integrated, Tally's stock is its stock ledger's opening and closing balance (1,500
    both, as its Profit and Loss shows): the closing balances validation uses take the same,
    and the stock-ledger-at-stock-value rule doesn't apply."""
    from connectors.tally.connector import _stock_and_difference, _stock_in_hand

    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=replay("not_integrated")
    )
    entity = connector.list_entities()[0]
    period = (entity.books_from, AS_OF)
    integrated = connector._integrated(entity)
    groups = connector._group_balances(entity, period)
    figures = connector._ledger_figures(entity, period, _stock_in_hand(groups), integrated)
    opening, closing, _ = _stock_and_difference(figures, None, groups)
    source = _source("not_integrated")
    assert (opening, closing) == (source.opening_stock, source.closing_stock)
    assert (opening, closing) == (Decimal(1500), Decimal(1500))


def test_validation_flags_a_line_that_differs_and_a_stock_value_that_changed(
    db: Session, books: S.Connection
) -> None:
    from dataclasses import replace

    from connectors.base import SourceControls
    from core.validation import Validator

    entity_id = db.scalars(select(A.Entity)).one().id
    source = _source("integrated")

    def validate(statements_then) -> list[str]:  # noqa: ANN001
        controls = SourceControls(statements={AS_OF: statements_then})
        report = Validator(db, entity_id, AS_OF, connection_id=books.id).run(
            None, controls=controls
        )
        return sorted({f.check_code for f in report.findings if f.severity == "error"})

    assert validate(source) == []
    stored = db.scalars(
        select(A.StockValue).where(A.StockValue.scope == "total", A.StockValue.as_of == AS_OF)
    ).one()
    assert (stored.opening_value, stored.closing_value) == (Decimal(2010), Decimal(5580))
    lines = tuple(
        replace(x, amount=x.amount + 1) if x.label == "Indirect Expenses" else x
        for x in source.lines
    )
    assert validate(replace(source, lines=lines)) == ["statement_mismatch"]
    changed = replace(source, closing_stock=Decimal(5581))
    assert "stock_value_mismatch" in validate(changed)


def test_a_source_without_the_reports_is_noted_not_failed(db: Session, books: S.Connection) -> None:
    """Tally rejects a report request it doesn't know (an older release, or a recording
    without them): the statements are noted as not supported, never a failure."""
    from connectors.base import SourceControls
    from core.validation import Validator
    from tests.conftest import FIXTURES

    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=FixtureTransport(FIXTURES / "tally")
    )
    entity = connector.list_entities()[0]
    assert connector.source_statements(entity, AS_OF) is None
    entity_id = db.scalars(select(A.Entity)).one().id
    controls = SourceControls(statements={AS_OF: None})  # type: ignore[dict-item]
    report = Validator(db, entity_id, AS_OF, connection_id=books.id).run(None, controls=controls)
    codes = {f.check_code: f.severity for f in report.findings}
    assert codes["statements_not_supported"] == "info"


def test_statement_dates_follow_the_reliable_dates() -> None:
    """Every month end, year end and the as-of date; in Educational mode a 30th becomes the
    2nd of the next month (the 1st isn't reliable for statements), never after the as-of
    date."""
    from core.dates import EDUCATIONAL, EVERY_DAY
    from workers.statements import statement_dates

    every = statement_dates(date(2026, 4, 1), 4, date(2026, 7, 15), EVERY_DAY)
    assert every == [date(2026, 4, 30), date(2026, 5, 31), date(2026, 6, 30), date(2026, 7, 15)]
    educational = statement_dates(date(2026, 4, 1), 4, date(2026, 7, 2), EDUCATIONAL)
    assert educational == [date(2026, 5, 2), date(2026, 5, 31), date(2026, 7, 2)]
