"""The Profit & Loss in Tally's layout (ADR-056) against Tally's own, recorded 2026-11-13 after
the PLS-* seed cases (tests/fixtures/tally/rules/pl_sides): every line of both sides (its
label, its side, its place and its amount), Gross Profit/Loss c/o and b/f, the subtotal, Nett
Profit/Loss and both Totals, at five dates, from the books' beginning and for the financial
year, with inventory integration on and off, against Tally's HTML export (the one that keeps
the sides; tests/tally_pl_html.py). The group amounts and the stock also equal Tally's XML.

The statements are stored as the statements refresh stores them, from the recorded XML. The
year end (31 March 2026) has no recording of its own: its closing stock is the opening stock
of Tally's financial-year report, which is the same value by definition."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.base import SourceStatements, StockFigure
from connectors.tally import reports
from core import statements
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.profit_loss_tally import TOTAL, TallyProfitLoss, drill, tally_profit_loss
from core.report_periods import Period
from tests.conftest import FIXTURES
from tests.stock_replay import FOLDER as EARLIER
from tests.tally_pl_html import read
from tests.test_statements import DATES as EARLIER_DATES
from tests.test_statements import _source as _earlier_source
from tests.test_statements import _synced

SIDES = FIXTURES / "tally" / "rules" / "pl_sides"
DATES = (date(2025, 12, 31), date(2026, 5, 31), date(2026, 10, 2), date(2026, 10, 31),
         date(2026, 11, 2))  # fmt: skip
BOOKS_FROM, YEAR_START, YEAR_END = date(2025, 4, 1), date(2026, 4, 1), date(2026, 3, 31)
CASES = ("integrated", "not_integrated")


def _source(case: str, on: date) -> SourceStatements:
    """Tally's statements for the date as the connector reads them, from the recording."""
    folder = SIDES / case
    pl = reports.profit_and_loss((folder / f"profit_and_loss_{on}.xml").read_bytes())
    sheet = reports.balance_sheet((folder / f"balance_sheet_{on}.xml").read_bytes())
    opening, closing = reports.stock_values(pl)
    return SourceStatements(
        as_of=on, lines=tuple(pl + sheet), opening_stock=opening, closing_stock=closing,
        stock=(StockFigure("total", "", opening, closing),), integrated=case == "integrated",
    )  # fmt: skip


def _year_end(case: str) -> SourceStatements:
    """31 March 2026: the books' opening stock, and the year's closing stock as Tally's
    financial-year report opens with it."""
    books = reports.stock_values(
        reports.profit_and_loss((SIDES / case / f"profit_and_loss_{DATES[1]}.xml").read_bytes())
    )
    year = reports.stock_values(
        reports.profit_and_loss((SIDES / case / f"fy_profit_and_loss_{DATES[1]}.xml").read_bytes())
    )
    return SourceStatements(
        as_of=YEAR_END, lines=(), opening_stock=books[0], closing_stock=year[0],
        stock=(StockFigure("total", "", books[0], year[0]),), integrated=case == "integrated",
    )  # fmt: skip


def _stored(db: Session, monkeypatch: pytest.MonkeyPatch, case: str) -> int:
    connection: S.Connection = _synced(db, monkeypatch, SIDES / case / "books")
    entity_id = db.scalars(select(A.Entity)).one().id
    for source in (_year_end(case), *(_source(case, on) for on in DATES)):
        statements.refresh(db, entity_id, connection.id, "live", source)
    return entity_id


def _sides(found: TallyProfitLoss) -> tuple[list, list]:
    """Ours as Tally's HTML lists each side: the gross block, its subtotal (no label), the
    net block and the Total; the total column's amounts (blank: None)."""
    sides = []
    for gross, net in ((found.gross.left, found.net.left), (found.gross.right, found.net.right)):
        rows = [(r.label, r.values.get(TOTAL)) for r in gross.rows]
        rows.append(("", gross.total[TOTAL]))
        rows += [(r.label, r.values.get(TOTAL)) for r in net.rows]
        rows.append(("Total", net.total[TOTAL]))
        sides.append(rows)
    return sides[0], sides[1]


def _periods() -> list[tuple[str, Period, date]]:
    found = [("", Period(BOOKS_FROM, on), on) for on in DATES]
    found += [("fy_", Period(YEAR_START, on), on) for on in DATES if on >= YEAR_START]
    return found


@pytest.mark.parametrize("case", CASES)
def test_every_line_equals_tallys_profit_and_loss_on_both_sides(
    db: Session, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """Eight reports per set-up (sixteen in all): five from the books' beginning, three for
    the year. Each side line by line: label, place and amount, blank where Tally is blank."""
    entity_id = _stored(db, monkeypatch, case)
    for prefix, period, on in _periods():
        tally = read(SIDES / case / f"{prefix}profit_and_loss_{on}.html")
        found = tally_profit_loss(db, [entity_id], period)
        assert found.reason is None, (prefix, on, found.reason)
        left, right = _sides(found)
        assert (left, right) == (tally.left, tally.right), (prefix, on)
        assert found.gross.left.total == found.gross.right.total  # the subtotal: equal
        assert found.net.left.total == found.net.right.total  # the Totals: equal


@pytest.mark.parametrize("case", CASES)
def test_group_amounts_and_stock_equal_tallys_xml(
    db: Session, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """From the books' beginning: each group's amount and the stock are Tally's XML lines
    (canonical sign: our left side positive, right side negative)."""
    entity_id = _stored(db, monkeypatch, case)
    for on in DATES:
        xml = {
            line.label.removeprefix("Add: ").removeprefix("Less: "): line.amount
            for line in reports.profit_and_loss(
                (SIDES / case / f"profit_and_loss_{on}.xml").read_bytes()
            )
            if line.label != "Cost of Sales :"
        }
        found = tally_profit_loss(db, [entity_id], Period(BOOKS_FROM, on))
        ours = {}
        for block in (found.gross, found.net):
            for sign, side in ((1, block.left), (-1, block.right)):
                for row in side.rows:
                    if row.kind == "group" and row.values[TOTAL] is not None:
                        ours[row.label] = row.values[TOTAL] * sign
        for label, amount in ours.items():
            assert amount == xml[label], (on, label)
        stock = {r.label: r.values[TOTAL] for r in found.gross.left.rows + found.gross.right.rows
                 if r.kind == "stock"}  # fmt: skip
        assert stock["Opening Stock"] == xml["Opening Stock"]
        # Tally writes the closing stock as a deduction with the opening stock's sign.
        assert stock["Closing Stock"] == xml["Closing Stock"]


def test_contrary_balances_sit_on_the_other_side(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2 November 2026 (the seed cases): sales and direct incomes in debit on the left,
    purchases and direct expenses in credit on the right, indirect incomes in debit on the
    left; a gross loss carried to the right and brought to the left; a nett loss on the
    right."""
    entity_id = _stored(db, monkeypatch, "integrated")
    found = tally_profit_loss(db, [entity_id], Period(BOOKS_FROM, date(2026, 11, 2)))
    labels = {
        side: [r.label for r in getattr(found.gross, side).rows + getattr(found.net, side).rows]
        for side in ("left", "right")
    }
    assert labels["left"] == [
        "Opening Stock", "Sales Accounts", "Direct Incomes",
        "Gross Loss b/f", "Indirect Incomes", "Indirect Expenses",
    ]  # fmt: skip
    assert labels["right"] == [
        "Purchase Accounts", "Direct Expenses", "Closing Stock", "Gross Loss c/o", "Nett Loss",
    ]  # fmt: skip
    assert found.net_profit[TOTAL] == Decimal(-59751)


def test_an_end_without_a_stored_statement_offers_the_nearest_dates(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    entity_id = _stored(db, monkeypatch, "integrated")
    found = tally_profit_loss(db, [entity_id], Period(YEAR_START, date(2026, 10, 20)))
    assert found.reason is not None and found.end is None
    assert found.nearest == [date(2026, 10, 2), date(2026, 10, 31)]


def test_a_line_drills_down_to_its_ledgers_and_adds_up(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each group line of the year to 2 November: its rows add up to it at every level, on
    its side (a contrary ledger negative)."""
    entity_id = _stored(db, monkeypatch, "integrated")
    period = Period(YEAR_START, date(2026, 11, 2))
    found = tally_profit_loss(db, [entity_id], period)
    checked = 0
    for side_name in ("left", "right"):
        for block in (found.gross, found.net):
            for row in getattr(block, side_name).rows:
                if row.kind != "group" or row.values[TOTAL] is None:
                    continue
                rows, reason = drill(db, [entity_id], period, row.group, side_name)
                assert reason is None
                assert rows[0].amount == row.values[TOTAL], row.label
                below: dict[str, Decimal] = {}
                for r in rows[1:]:
                    below[r.parent] = below.get(r.parent, Decimal(0)) + r.amount
                for r in rows:
                    if r.key in below:
                        assert below[r.key] == r.amount, r.label
                assert any(r.kind == "ledger" and r.ledger_id for r in rows)
                checked += 1
    assert checked >= 6


def test_several_companies_have_a_column_each_and_a_total(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One column per company and a total: with one company, the two are equal."""
    entity_id = _stored(db, monkeypatch, "integrated")
    period = Period(BOOKS_FROM, date(2026, 10, 2))
    alone = tally_profit_loss(db, [entity_id], period)
    assert alone.columns == [f"company:{entity_id}", TOTAL]
    for row in alone.gross.left.rows:
        assert row.values[f"company:{entity_id}"] == row.values[TOTAL]


@pytest.mark.parametrize("case", ["integrated", "not_integrated"])
@pytest.mark.parametrize("on", EARLIER_DATES)
def test_the_earlier_recordings_amounts_equal_tallys_xml(
    db: Session, monkeypatch: pytest.MonkeyPatch, case: str, on: date
) -> None:
    """The first statement recordings (2026-10-22, stock_values): every group and the stock
    of the layout equal Tally's own Profit and Loss lines."""
    connection: S.Connection = _synced(db, monkeypatch, EARLIER / "books")
    entity_id = db.scalars(select(A.Entity)).one().id
    source = _earlier_source(case, on, EARLIER)
    statements.refresh(db, entity_id, connection.id, "live", source)
    xml = {
        line.label.removeprefix("Add: ").removeprefix("Less: "): line.amount
        for line in source.lines
        if line.statement == "profit_loss" and line.label != "Cost of Sales :"
    }
    found = tally_profit_loss(db, [entity_id], Period(on.replace(month=4, day=1), on))
    assert found.reason is None
    for block in (found.gross, found.net):
        for sign, side in ((1, block.left), (-1, block.right)):
            for row in side.rows:
                if row.kind == "group" and row.values[TOTAL] is not None:
                    assert row.values[TOTAL] * sign == xml[row.label], (on, row.label)
                elif row.kind == "stock":
                    assert row.values[TOTAL] == xml[row.label], (on, row.label)


def test_the_api_serves_the_layout_the_nearest_dates_and_a_drill_down(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/v1/reports/profit-loss/tally and .../drill: both sides with the totals, the
    nearest stored dates for an end between them, a line's ledgers."""
    from fastapi.testclient import TestClient

    from api.deps import get_report_session
    from api.main import create_app

    _stored(db, monkeypatch, "integrated")
    app = create_app()
    app.dependency_overrides[get_report_session] = lambda: db
    api = TestClient(app, base_url="http://localhost")
    found = api.get(
        "/api/v1/reports/profit-loss/tally",
        params={"date_from": "2026-04-01", "date_to": "2026-11-02"},
    ).json()
    assert found["reason"] is None and [c["label"] for c in found["columns"]][-1] == "Total"
    assert found["net"]["right"]["rows"][-1]["label"] == "Nett Loss"
    assert found["net"]["left"]["total"] == found["net"]["right"]["total"]
    between = api.get(
        "/api/v1/reports/profit-loss/tally",
        params={"date_from": "2026-04-01", "date_to": "2026-10-20"},
    ).json()
    assert between["gross"] is None and between["nearest"] == ["2026-10-02", "2026-10-31"]
    sales = next(r for r in found["gross"]["left"]["rows"] if r["label"] == "Sales Accounts")
    rows = api.get(
        "/api/v1/reports/profit-loss/drill",
        params={"date_from": "2026-04-01", "date_to": "2026-11-02", "group": sales["group"],
                "side": "left"},
    ).json()["rows"]  # fmt: skip
    assert rows[0]["amount"] == sales["values"]["total"]
    assert any(r["kind"] == "ledger" for r in rows)
