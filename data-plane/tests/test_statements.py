"""Statements built from our books against the source's own (ADR-040; RPT-012, VAL-015), on
the test company's recordings of 2026-10-22: its books (stock_values/books) and its
statements with accounts integrated with inventory and without (stock_values/integrated,
stock_values/not_integrated); and after the statement layout seed of 2026-10-23
(statement_layout/books, statement_layout/integrated: Direct Expenses and Direct Incomes, a
foreign-currency gain beside a loss, an opening balance on Profit & Loss A/c)."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.tally.connector import TallyConnector
from connectors.tally.fixtures import FixtureTransport
from core import statements
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from tests.conftest import COMPANY
from tests.stock_replay import FOLDER, LAYOUT, NETTING, YEAR_END, replay
from workers.extract import get_or_create_connection
from workers.sync import run_sync

AS_OF = date(2026, 10, 2)
DATES = (date(2026, 4, 1), date(2026, 5, 31), date(2026, 8, 31), AS_OF)


def _synced(db: Session, monkeypatch: pytest.MonkeyPatch, folder: Path) -> S.Connection:
    monkeypatch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )
    connection = get_or_create_connection(db, "tally-test", "tally")
    db.commit()
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=FixtureTransport(folder)
    )
    result = run_sync(db, connection, connector, [COMPANY])
    assert result.status == "succeeded" and result.failed == 0
    return connection


@pytest.fixture
def books(db: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[S.Connection]:
    """The test company's books as recorded on the day its statements were."""
    yield _synced(db, monkeypatch, FOLDER / "books")


@pytest.fixture
def year_end_books(db: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[S.Connection]:
    """The test company's books after the year-end seed: books from 1 April 2025 (2026-10-24)."""
    yield _synced(db, monkeypatch, YEAR_END / "books")


@pytest.fixture
def netting_books(db: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[S.Connection]:
    """The test company's books after the netting seed (2026-10-24)."""
    yield _synced(db, monkeypatch, NETTING / "books")


@pytest.fixture
def layout_books(db: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[S.Connection]:
    """The test company's books after the statement layout seed (2026-10-23)."""
    yield _synced(db, monkeypatch, LAYOUT / "books")


def _source(case: str, as_of: date = AS_OF, root: Path = FOLDER):  # noqa: ANN202
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000", "educational": "yes"}, transport=replay(case, root)
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


@pytest.mark.parametrize("as_of", [date(2026, 8, 31), AS_OF])
def test_direct_lines_forex_gains_and_an_accumulated_profit_match_the_source(
    db: Session, layout_books: S.Connection, as_of: date
) -> None:
    """Tally's layout, recorded after the statement layout seed: Direct Expenses inside Cost
    of Sales (after Closing Stock), Direct Incomes on its own line, the Trial Balance's
    Unadjusted Forex Gain/Loss with the losses as a debit and the gains as a credit (the
    Balance Sheet shows the net), and Profit & Loss A/c's opening balance in the account."""
    entity_id = db.scalars(select(A.Entity)).one().id
    source = _source("integrated", as_of, LAYOUT)
    result = statements.refresh(db, entity_id, layout_books.id, "live", source)
    listed = [(d.statement, d.key, str(d.ours), str(d.source)) for d in result.differences]
    assert listed == []


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


# --- the pilot-safe summary of differences (core/statement_differences.py) ----------------


def _old_layout(source):  # noqa: ANN001, ANN202
    """The source's lines as we laid them out before 2026-10-23 (Direct Expenses beside
    Cost of Sales, one net forex line in the Trial Balance), with three more lines: a
    renamed reserved group, a custom group and a ledger name."""
    from dataclasses import replace

    from connectors.base import StatementLine

    lines = []
    for x in source.lines:
        if x.statement == "profit_loss" and x.label == "Cost of Sales :":
            lines.append(replace(x, amount=x.amount - 300))
        elif x.statement == "profit_loss" and x.label == "Direct Expenses":
            lines.append(replace(x, level="main"))
        elif x.statement == "trial_balance" and x.label == "Unadjusted Forex Gain/Loss":
            lines.append(replace(x, amount=Decimal(4100), debit=Decimal(4100), credit=Decimal(0)))
        else:
            lines.append(x)
    lines += [
        StatementLine("balance_sheet", "Inventories", "main", Decimal(7)),
        StatementLine("balance_sheet", "Client Shelf Group", "main", Decimal(11)),
        StatementLine("trial_balance", "Customer Delta USD", "main", Decimal(13), Decimal(13), 0),
    ]
    return replace(source, lines=tuple(lines))


def test_the_summary_names_each_line_safely_and_what_it_equals(
    db: Session, layout_books: S.Connection
) -> None:
    """Every differing line once, with the dates and what the difference equals; custom
    names never shown: a renamed reserved group by its reserved name, a custom group by the
    reserved group above it, anything else unnamed."""
    from core.statement_differences import Summary

    entity_id = db.scalars(select(A.Entity)).one().id
    current = db.scalars(
        select(A.AccountGroup).where(A.AccountGroup.name == "Current Assets")
    ).one()
    db.add(
        A.AccountGroup(
            entity_id=entity_id, name="Client Shelf Group", parent_id=current.id,
            source_key="custom-1", connection_id=layout_books.id, origin="live",
        )
    )  # fmt: skip
    db.commit()
    summary = Summary()
    for on in (date(2026, 8, 31), AS_OF):
        source = _old_layout(_source("integrated", on, LAYOUT))
        summary.add(
            db,
            entity_id,
            source,
            statements.refresh(db, entity_id, layout_books.id, "live", source),
        )
    lines = summary.lines()
    text = "\n".join(lines)
    for name in ("Client Shelf Group", "Inventories", "Customer Delta USD"):
        assert name not in text
    cost_of_sales = "Profit & loss: Cost of Sales: different amount at 2 of 2 dates"
    assert f"{cost_of_sales}; equals Direct Expenses at 1" in lines  # from September only
    forex = [x for x in lines if "Unadjusted Forex" in x]  # taken from the source: reported
    assert forex and all("taken from the source, ours computed differs" in x for x in forex)
    assert any(
        x.startswith("Balance sheet: Stock-in-Hand (renamed): missing in ours") for x in lines
    )
    assert any(
        x.startswith("Balance sheet: a custom group under Current Assets: missing in ours")
        for x in lines
    )
    assert any(
        x.startswith("Trial balance: a line not recognised (debit): missing in ours") for x in lines
    )


def test_validation_prints_the_summary(db: Session, layout_books: S.Connection) -> None:
    from connectors.base import SourceControls
    from core.validation import Validator

    entity_id = db.scalars(select(A.Entity)).one().id
    source = _old_layout(_source("integrated", AS_OF, LAYOUT))
    controls = SourceControls(statements={AS_OF: source})
    report = Validator(db, entity_id, AS_OF, connection_id=layout_books.id).run(
        None, controls=controls
    )
    assert any(x.startswith("Profit & loss: Cost of Sales:") for x in report.statement_summary)
    clean = SourceControls(statements={AS_OF: _source("integrated", AS_OF, LAYOUT)})
    report = Validator(db, entity_id, AS_OF, connection_id=layout_books.id).run(
        None, controls=clean
    )
    assert report.statement_summary == []


def test_the_last_year_end_gives_its_profit_and_stock(
    db: Session, layout_books: S.Connection
) -> None:
    """After a year end the summary also tests the profit up to it and since, and the
    stock stored for it (read by the year end's own statements)."""
    from core.statement_differences import YearEnd, last_year_end, tested_amounts

    entity = db.scalars(select(A.Entity)).one()
    source = _source("integrated", AS_OF, LAYOUT)
    f = statements.figures(db, entity.id, source)
    assert last_year_end(db, entity.id, f) == YearEnd()  # books from April 2026: none yet
    entity.books_from = date(2025, 4, 1)
    db.add(
        A.StockValue(
            entity_id=entity.id, connection_id=layout_books.id, origin="live",
            as_of=date(2026, 3, 31), scope="total", scope_name="",
            opening_value=Decimal(2010), closing_value=Decimal(2500), read_at=source.as_of,
        )
    )  # fmt: skip
    db.commit()
    year_end = last_year_end(db, entity.id, f)
    assert year_end.stock == Decimal(2500)
    assert year_end.profit == Decimal(2010) - Decimal(2500)  # no vouchers before April 2026
    tested = tested_amounts(f, year_end)
    assert tested["the stock at the last year end less the opening stock"] == Decimal(490)
    assert tested["the profit since the last year end"] == tested["the net profit"] + 490
    assert tested["Direct Expenses"] == Decimal(300) and tested["Direct Incomes"] == Decimal(-120)
    assert tested["the foreign-currency losses"] == Decimal(8200)
    assert tested["the foreign-currency gains"] == Decimal(-4100)
    assert tested["Profit & Loss A/c's own balance"] == Decimal(-3000)


def test_tally_splits_a_trial_balance_line_ledger_by_ledger(
    db: Session, layout_books: S.Connection
) -> None:
    """Current Liabilities holds Duties & Taxes with input tax ledgers (debit) and output
    tax ledgers (credit): Tally's Trial Balance shows 2,340 Dr and 26,129 Cr, ledger by
    ledger. Netting each sub-group first (the summary's tested split) would give 0 Dr."""
    from core.statement_differences import netted_split

    entity_id = db.scalars(select(A.Entity)).one().id
    source = _source("integrated", AS_OF, LAYOUT)
    f = statements.figures(db, entity_id, source)
    line = next(x for _, x in statements.trial_balance(f) if x.label == "Current Liabilities")
    theirs = next(
        x for x in source.lines if x.statement == "trial_balance" and x.label == line.label
    )
    assert (
        (line.debit, line.credit)
        == (theirs.debit, theirs.credit)
        == (Decimal(2340), Decimal(26129))
    )
    group = next(g.id for g in f.groups.values() if g.name == "Current Liabilities")
    assert netted_split(f, group) == {"debit": Decimal(0), "credit": Decimal(23789)}


def test_stock_candidates_are_read_after_the_first_year_end() -> None:
    """Integrated, after a year end: Tally's Stock-in-Hand group, the items' value and the
    current financial year's own closing stock, for the summary (on the test company all
    equal the Profit and Loss's 6,840). Before the year end: none."""
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000", "educational": "yes"},
        transport=replay("integrated", YEAR_END),
    )
    entity = connector.list_entities()[0]
    assert connector._year_start(entity, AS_OF) == date(2026, 4, 1)
    assert connector.source_statements(entity, date(2026, 3, 2)).stock_candidates == {}
    found = connector.source_statements(entity, AS_OF).stock_candidates
    assert set(found.values()) == {Decimal(6840)}
    assert set(found) == {
        "Stock-in-Hand's closing balance",
        "the stock items' closing value",
        "this financial year's closing stock",
    }


def test_a_group_netted_for_reporting_is_one_figure_in_the_trial_balance(
    db: Session, netting_books: S.Connection
) -> None:
    """The netting seed (2026-10-24): under Current Assets a group set to net its balances
    for reporting (ISADDABLE: 400 Dr and 150 Cr shown as 250 Dr), a group behaving like a
    sub-ledger and a plain one (both split: 200 Dr / 90 Cr, 300 Dr / 120 Cr); a vendor
    with an advance inside Sundry Creditors (sub-ledger, still split: 700 Dr). Tally's Trial
    Balance: Current Assets 72,518 Dr and 210 Cr, Current Liabilities 3,040 Dr."""
    entity_id = db.scalars(select(A.Entity)).one().id
    source = _source("integrated", AS_OF, NETTING)
    assert len(source.netted_groups) == 1
    result = statements.refresh(db, entity_id, netting_books.id, "live", source)
    listed = [(d.statement, d.key, str(d.ours), str(d.source)) for d in result.differences]
    assert listed == []
    ours = {
        x.label: (x.debit, x.credit)
        for _, x in statements.trial_balance(statements.figures(db, entity_id, source))
    }
    assert ours["Current Assets"] == (Decimal(72518), Decimal(210))
    assert ours["Current Liabilities"] == (Decimal(3040), Decimal(26129))


YEAR_END_DATES = (
    date(2025, 9, 2), date(2026, 3, 2), date(2026, 3, 31), date(2026, 5, 2),
    date(2026, 8, 31), AS_OF,
)  # fmt: skip


@pytest.mark.parametrize("case", ["integrated", "not_integrated"])
@pytest.mark.parametrize("as_of", YEAR_END_DATES)
def test_statements_match_across_the_year_end(
    db: Session, year_end_books: S.Connection, case: str, as_of: date
) -> None:
    """Books from 1 April 2025, a year end on 31 March 2026: before it, on it and after."""
    entity_id = db.scalars(select(A.Entity)).one().id
    source = _source(case, as_of, YEAR_END)
    result = statements.refresh(db, entity_id, year_end_books.id, "live", source)
    listed = [(d.statement, d.key, str(d.ours), str(d.source)) for d in result.differences]
    assert listed == []


def test_the_forex_line_is_taken_from_the_source_and_ours_kept_as_detail(
    db: Session, layout_books: S.Connection
) -> None:
    """Fallback (2026-10-24): the Unadjusted Forex Gain/Loss line is the source's own,
    labelled "(taken from the source)"; ours, computed (losses as the debit, gains as the
    credit), stays beside it as a detail line, never compared."""
    entity_id = db.scalars(select(A.Entity)).one().id
    source = _source("integrated", AS_OF, LAYOUT)
    lines = {(x.statement, x.label): x for _, x in statements.build(db, entity_id, source)}
    taken = lines[("trial_balance", "Unadjusted Forex Gain/Loss (taken from the source)")]
    assert (taken.level, taken.debit, taken.credit) == ("main", Decimal(8200), Decimal(4100))
    computed = lines[("trial_balance", "Unadjusted Forex Gain/Loss (computed)")]
    assert (computed.level, computed.debit, computed.credit) == (
        "detail", Decimal(8200), Decimal(4100),
    )  # fmt: skip
    assert (
        lines[("balance_sheet", "Unadjusted Forex Gain/Loss (taken from the source)")].amount
        == 4100
    )
    assert statements.match_key(taken.label) == "unadjusted forex gain/loss"


def test_without_integration_the_balance_sheet_takes_the_closing_stock_too(
    db: Session, books: S.Connection
) -> None:
    """Not integrated, Tally's stock can be closing values entered on the stock ledger by
    date rather than its balance (pilot 2026-10-24: a Balance Sheet differing by the stock
    at the last year end less the opening stock). The stock ledgers count at the source's
    stock: its opening in the Trial Balance, its closing in the Balance Sheet."""
    from dataclasses import replace

    entity_id = db.scalars(select(A.Entity)).one().id
    source = _source("not_integrated")
    entered = replace(source, closing_stock=Decimal(1800))  # 1,500 in the ledger's balance

    def line(src, statement: str, label: str):  # noqa: ANN001, ANN202
        return next(x for _, x in statements.build(db, entity_id, src)
                    if x.statement == statement and x.label == label)  # fmt: skip

    before = line(source, "balance_sheet", "Current Assets").amount
    assert line(entered, "balance_sheet", "Current Assets").amount == before + 300
    tb = line(entered, "trial_balance", "Current Assets")
    assert (tb.debit, tb.credit) == (Decimal(72678), Decimal(0))  # the opening stock: 1,500


def test_after_the_year_end_the_balance_sheet_stock_line_is_taken_from_the_source(
    db: Session, year_end_books: S.Connection
) -> None:
    """Integrated, after the first year end, the line holding the stock is the source's
    (ours kept as detail); a taken line that differs from ours is reported by the summary
    with what the difference equals, never as a statement difference."""
    from dataclasses import replace

    from core.statement_differences import Summary

    entity_id = db.scalars(select(A.Entity)).one().id
    before = statements.build(db, entity_id, _source("integrated", date(2026, 3, 2), YEAR_END))
    assert any(x.label == "Current Assets" and x.level == "main" for _, x in before)
    source = _source("integrated", AS_OF, YEAR_END)
    lines = {x.label: x for _, x in statements.build(db, entity_id, source)}
    taken = lines["Current Assets (taken from the source)"]
    assert taken.level == "main" and lines["Current Assets (computed)"].amount == taken.amount
    # Tally's Balance Sheet stock 500 above the Profit and Loss's (6,840):
    shifted = tuple(
        replace(x, amount=x.amount + 500)
        if x.statement == "balance_sheet" and x.label == "Current Assets"
        else x
        for x in source.lines
    )
    candidates = {**source.stock_candidates, "Stock-in-Hand's closing balance": Decimal(7340)}
    changed = replace(source, lines=shifted, stock_candidates=candidates)
    result = statements.refresh(db, entity_id, year_end_books.id, "live", changed)
    assert result.differences == []  # the line is the source's, so the totals agree too
    assert [(d.key, d.kind) for d in result.taken] == [("current assets:amount", "taken")]
    summary = Summary()
    summary.add(db, entity_id, changed, result)
    assert any(
        x.startswith("Balance sheet: Current Assets: taken from the source, ours computed")
        and "the closing stock less Stock-in-Hand's closing balance at 1" in x
        for x in summary.lines()
    )
