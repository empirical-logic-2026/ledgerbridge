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
from tests.stock_replay import FOLDER, LAYOUT, replay
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
    assert any(  # the vendor's gain exists from 1 September only
        x.startswith("Trial balance: Unadjusted Forex Gain/Loss (credit): different amount at 1")
        and "minus the foreign-currency gains at 1" in x
        for x in lines
    )
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


def test_stock_candidates_are_read_after_the_first_year_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Integrated, after a year end: Tally's Stock-in-Hand group, the items' value and the
    current financial year's own closing stock, for the summary. Before it: none."""
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000", "educational": "yes"}, transport=replay("integrated")
    )
    entity = connector.list_entities()[0]
    assert connector._year_start(entity, AS_OF) == date(2026, 4, 1)
    assert connector.source_statements(entity, AS_OF).stock_candidates == {}  # first year
    monkeypatch.setattr(connector, "_year_start", lambda entity, on: date(2026, 6, 1))
    found = connector._stock_candidates(entity, (entity.books_from, AS_OF))
    assert found == {
        "Stock-in-Hand's closing balance": Decimal(5580),
        "the stock items' closing value": Decimal(5580),
        "this financial year's closing stock": Decimal(5580),  # the recording's own P&L
    }
