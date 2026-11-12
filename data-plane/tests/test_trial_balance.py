"""The Trial Balance page against Tally's own Trial Balance (ADR-055), on the test company's
recordings: line by line and in total at every recorded date, condensed (groups) and
detailed (every group and ledger against Tally's group and ledger balances).

- Within the first financial year (stock_values, statement_layout, statement_netting and the
  year-end set before 1 April 2026) Tally's Trial Balance from the books' beginning is the
  one for the year.
- After the year end of 31 March 2026 (statement_year_end, books from 1 April 2025) the page
  equals Tally's Trial Balance for the financial year (the fy_ recordings, 2026-04-01 to the
  date), not the one from the books' beginning that the stored statements are checked
  against: the reason the pilot's Trial Balance differed from Tally's."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.tally import envelopes, reports
from connectors.tally.connector import TallyConnector, _canonical
from core import statements
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.statements import match_key
from core.trial_balance import trial_balance
from tests.stock_replay import FOLDER, LAYOUT, NETTING, YEAR_END, replay
from tests.test_statements import AS_OF, DATES, YEAR_END_DATES, _source, _synced
from workers.trial_balance import print_trial_balance

YEAR_START = date(2026, 4, 1)


@pytest.fixture
def books(db: Session, monkeypatch: pytest.MonkeyPatch) -> S.Connection:
    """The test company's books as recorded with its first statements (2026-10-22)."""
    return _synced(db, monkeypatch, FOLDER / "books")


@pytest.fixture
def layout_books(db: Session, monkeypatch: pytest.MonkeyPatch) -> S.Connection:
    """After the statement layout seed (2026-10-23)."""
    return _synced(db, monkeypatch, LAYOUT / "books")


@pytest.fixture
def netting_books(db: Session, monkeypatch: pytest.MonkeyPatch) -> S.Connection:
    """After the netting seed (2026-10-24)."""
    return _synced(db, monkeypatch, NETTING / "books")


@pytest.fixture
def year_end_books(db: Session, monkeypatch: pytest.MonkeyPatch) -> S.Connection:
    """After the year-end seed: books from 1 April 2025 (2026-10-24)."""
    return _synced(db, monkeypatch, YEAR_END / "books")


AFTER_YEAR_END = tuple(d for d in YEAR_END_DATES if d >= YEAR_START)


def _tally_lines(path: Path) -> dict[str, tuple[Decimal, Decimal]]:
    """Tally's Trial Balance lines with an amount: match key -> (debit, credit)."""
    return {
        match_key(x.label): (x.debit or Decimal(0), x.credit or Decimal(0))
        for x in reports.trial_balance(path.read_bytes())
        if x.level == "main" and (x.debit or x.credit)
    }


def _ours(db: Session, as_of: date) -> tuple[dict[str, tuple[Decimal, Decimal]], object]:
    entity_id = db.scalars(select(A.Entity)).one().id
    found = trial_balance(db, [entity_id], as_of)
    assert found.reason is None, found.reason
    lines = {match_key(r.label): (r.debit, r.credit) for r in found.lines if r.debit or r.credit}
    return lines, found


def _refresh(db: Session, connection: S.Connection, case: str, root: Path, dates) -> None:  # noqa: ANN001
    entity_id = db.scalars(select(A.Entity)).one().id
    for as_of in dates:
        statements.refresh(db, entity_id, connection.id, "live", _source(case, as_of, root))


def _assert_equal(ours: dict, theirs: dict, found) -> None:  # noqa: ANN001
    """Line by line, and the totals of each column as Tally's lines add up."""
    assert ours == theirs
    assert found.debit == sum(d for d, _ in theirs.values())
    assert found.credit == sum(c for _, c in theirs.values())
    difference = found.difference
    if found.debit == found.credit:
        assert difference is None
    else:  # its own row, so debit and credit with it are equal
        assert found.debit + difference.debit == found.credit + difference.credit


@pytest.mark.parametrize("case", ["integrated", "not_integrated"])
@pytest.mark.parametrize("as_of", DATES)
def test_within_the_first_year_it_equals_tallys_trial_balance(
    db: Session,
    books: S.Connection,
    case: str,
    as_of: date,
) -> None:
    _refresh(db, books, case, FOLDER, [as_of])
    ours, found = _ours(db, as_of)
    assert found.year_start is None  # the first financial year: from the books' beginning
    _assert_equal(ours, _tally_lines(FOLDER / case / f"trial_balance_{as_of}.xml"), found)


@pytest.mark.parametrize("as_of", [date(2026, 8, 31), AS_OF])
def test_forex_lines_direct_lines_and_a_profit_carrier_equal_tallys(
    db: Session,
    layout_books: S.Connection,
    as_of: date,
) -> None:
    """The layout seed: Unadjusted Forex Gain/Loss (losses as debit, gains as credit) and an
    opening balance on Profit & Loss A/c."""
    _refresh(db, layout_books, "integrated", LAYOUT, [as_of])
    ours, found = _ours(db, as_of)
    _assert_equal(ours, _tally_lines(LAYOUT / "integrated" / f"trial_balance_{as_of}.xml"), found)


def test_a_group_netted_for_reporting_is_one_figure(
    db: Session,
    netting_books: S.Connection,
) -> None:
    _refresh(db, netting_books, "integrated", NETTING, [AS_OF])
    ours, found = _ours(db, AS_OF)
    _assert_equal(ours, _tally_lines(NETTING / "integrated" / f"trial_balance_{AS_OF}.xml"), found)
    assert ours["current assets"] == (Decimal(72518), Decimal(210))


@pytest.mark.parametrize("case", ["integrated", "not_integrated"])
def test_after_the_year_end_it_equals_tallys_trial_balance_for_the_year(
    db: Session,
    year_end_books: S.Connection,
    case: str,
) -> None:
    """Every recorded date of the year-end set: before 1 April 2026 Tally's Trial Balance
    from the books' beginning, after it Tally's for the financial year 2026-27."""
    _refresh(db, year_end_books, case, YEAR_END, YEAR_END_DATES)
    for as_of in YEAR_END_DATES:
        ours, found = _ours(db, as_of)
        prefix = "fy_" if as_of >= YEAR_START else ""
        theirs = _tally_lines(YEAR_END / case / f"{prefix}trial_balance_{as_of}.xml")
        assert found.year_start == (YEAR_START if as_of >= YEAR_START else None), as_of
        _assert_equal(ours, theirs, found)


def test_the_year_view_differs_from_the_books_view_by_the_rules(
    db: Session,
    year_end_books: S.Connection,
) -> None:
    """2 May 2026: the lines the pilot saw differ, each by its rule (F-TB-003 to F-TB-005)."""
    _refresh(db, year_end_books, "integrated", YEAR_END, YEAR_END_DATES)
    ours, _ = _ours(db, date(2026, 5, 2))
    books_view = _tally_lines(YEAR_END / "integrated" / "trial_balance_2026-05-02.xml")
    changed = {k for k in ours if ours[k] != books_view.get(k)}
    assert changed == {"current assets", "sales accounts", "purchase accounts", "profit & loss a/c"}
    assert ours["sales accounts"] == (Decimal(0), Decimal(12000))  # this year only
    assert ours["profit & loss a/c"] == (Decimal(0), Decimal(4770))  # 3,000 + last year's 1,770


def test_the_command_prints_it_in_tallys_layout(
    db: Session,
    year_end_books: S.Connection,
) -> None:
    """`./dev.ps1 trial-balance`: the last stored date on or before the one asked for, the
    financial year, the lines with debit and credit, the totals; detailed adds the ledgers."""
    _refresh(db, year_end_books, "integrated", YEAR_END, YEAR_END_DATES)
    entity_id = db.scalars(select(A.Entity)).one().id
    printed: list[str] = []
    code = print_trial_balance(db, entity_id, "Test Co", date(2026, 5, 10), False, printed.append)
    text = "\n".join(printed)
    assert code == 0
    assert "From 01-Apr-2026 to 02-May-2026 (screen only; not stored)" in text
    assert any(x.startswith("Sales Accounts") and x.rstrip().endswith("12,000.00") for x in printed)
    assert any(x.startswith("Total") and x.count("1,75,680.00") + x.count("175,680.00") == 2
               for x in printed)  # fmt: skip
    detailed: list[str] = []
    print_trial_balance(db, entity_id, "Test Co", date(2026, 5, 10), True, detailed.append)
    assert len(detailed) > len(printed)
    assert any(x.startswith("  ") and "Opening stock" in x for x in detailed)
    nothing: list[str] = []
    assert (
        print_trial_balance(db, entity_id, "Test Co", date(2025, 1, 1), False, nothing.append) == 2
    )


@pytest.mark.parametrize("case", ["integrated", "not_integrated"])
@pytest.mark.parametrize("as_of", AFTER_YEAR_END)
def test_detailed_every_group_and_ledger_equals_tallys_balances_for_the_year(
    db: Session,
    year_end_books: S.Connection,
    case: str,
    as_of: date,
) -> None:
    """Each ledger row equals Tally's ledger balance for the year, and each group row Tally's
    group balance, except the groups holding the stock: Tally's group balance there has the
    closing stock, its Trial Balance the opening stock."""
    _refresh(db, year_end_books, case, YEAR_END, YEAR_END_DATES)
    _, found = _ours(db, as_of)
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000", "educational": "yes"}, transport=replay(case, YEAR_END)
    )
    entity = connector.list_entities()[0]
    period = (YEAR_START, as_of)
    ledgers = {
        match_key(x.get("NAME") or ""): _canonical(x.findtext("CLOSINGBALANCE"))
        for x in connector._export_objects(
            entity, envelopes.LEDGER_BALANCES, balances_period=period
        )
    }
    groups = {match_key(g.name): g.closing for g in connector._group_balances(entity, period)}
    stock_path = {r.parent for r in found.rows if r.kind == "stock"}
    stock_path |= {r.key for r in found.rows if r.kind == "group" and any(
        s and s.startswith(r.key + "/") or s == r.key for s in stock_path)}  # fmt: skip
    checked = 0
    for row in found.rows:
        if row.kind == "ledger":
            assert row.amount == ledgers[match_key(row.label)], row.label
            checked += 1
        elif row.kind == "group" and row.key not in stock_path:
            assert row.amount == groups[match_key(row.label)], row.label
            checked += 1
    assert checked > 20
