"""Receivables and payables with ageing (core/ageing.py; F-PTY-013 to F-PTY-019), proved
against Tally's own figures on the test company: the total outstanding equals the closing
balance of Tally's Sundry Debtors (Sundry Creditors) group, as recorded with its statements
(group_balance_<date>.xml), at every recorded date. The netting recording (02-Oct-2026) has a
vendor in debit (an advance), so the payables are Tally's net figure."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from connectors.tally import envelopes, parser
from core import statements
from core.ageing import BUCKETS, OVER_90, AgeingRow, OpenBill, ageing, bucket
from core.models import accounting as A  # noqa: N812
from tests.stock_replay import FOLDER, NETTING
from tests.test_statements import _source, _synced

D = Decimal


def _tally_group(folder: Path, on: date, group: str) -> Decimal:
    """A group's closing balance as Tally recorded it (debit positive)."""
    body = (folder / "integrated" / f"group_balance_{on:%Y-%m-%d}.xml").read_bytes()
    for g in parser.objects(parser.parse_response(body), envelopes.GROUP_BALANCES.object_tag):
        if parser.object_name(g) == group:
            return -D(g.findtext("CLOSINGBALANCE") or "0")  # Tally: a debit is negative
    raise AssertionError(f"{group} not recorded on {on}")


@pytest.mark.parametrize(
    ("folder", "on"),
    [
        (FOLDER, date(2026, 5, 31)),
        (FOLDER, date(2026, 8, 31)),
        (FOLDER, date(2026, 10, 2)),
        (NETTING, date(2026, 10, 2)),
    ],
)
def test_the_totals_equal_tallys_sundry_debtors_and_creditors(
    db: Session, monkeypatch: pytest.MonkeyPatch, folder: Path, on: date
) -> None:
    connection = _synced(db, monkeypatch, folder / "books")
    companies = [db.query(A.Entity).one().id]
    # Tally's statements for the date, as `./dev.ps1 statements` stores them: with them the
    # foreign-currency parties' revalued balances, as Tally's Balance Sheet shows them.
    statements.refresh(db, companies[0], connection.id, "live", _source("integrated", on, folder))
    receivables = ageing(db, companies, on, "customers").total()
    payables = ageing(db, companies, on, "vendors").total()
    assert receivables.balance == _tally_group(folder, on, "Sundry Debtors")
    assert payables.balance == -_tally_group(folder, on, "Sundry Creditors")  # a credit
    # The bills and what isn't in them make up the balance, in each total.
    for total in (receivables, payables):
        assert total.bills + total.uncovered == total.balance
        parts = total.on_account + total.opening_difference + total.revaluation + total.other
        assert parts == total.uncovered


def test_netting_has_a_vendor_in_advance(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _synced(db, monkeypatch, NETTING / "books")
    companies = [db.query(A.Entity).one().id]
    on = date(2026, 10, 2)
    statements.refresh(db, companies[0], connection.id, "live", _source("integrated", on, NETTING))
    found = ageing(db, companies, date(2026, 10, 2), "vendors")
    advance = next(r for r in found.rows if r.name == "Vendor Foxtrot Advance")
    assert advance.balance < 0  # we paid in advance: a debit on a vendor
    assert found.total().balance == D(6450)


@pytest.mark.parametrize(
    ("days", "name"),
    [(-5, "not_due"), (0, "not_due"), (1, "days_1_30"), (30, "days_1_30"), (31, "days_31_60"),
     (60, "days_31_60"), (61, "days_61_90"), (90, "days_61_90"), (91, "days_91_180"),
     (180, "days_91_180"), (181, "over_180")],
)  # fmt: skip
def test_six_buckets(days: int, name: str) -> None:
    assert bucket(days) == name
    assert set(OVER_90) <= set(BUCKETS) and len(BUCKETS) == 6


def _bill(amount: str, days: int, overdue_days: int) -> OpenBill:
    day = date(2026, 1, 1)
    return OpenBill(1, "Synthetic party", "B", day, day, D(amount), days, overdue_days, None)


def test_overdue_is_by_due_date_whatever_the_basis() -> None:
    """Aged by the bill's date (120 days old) but due in 10 days: in 91-180, not overdue."""
    row = AgeingRow(1, "Synthetic party", D(100))
    row.add_outstanding(_bill("100", 120, 0))
    assert row.buckets["days_91_180"] == D(100) and row.over_90 == D(100)
    assert (row.overdue, row.pending) == (D(0), D(100))


def test_by_bill_date_ages_from_the_bills_date(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _synced(db, monkeypatch, FOLDER / "books")
    companies = [db.query(A.Entity).one().id]
    on = date(2026, 10, 2)
    by_due = ageing(db, companies, on, "customers")
    by_bill = ageing(db, companies, on, "customers", basis="bill_date")
    assert by_due.total().balance == by_bill.total().balance
    assert by_due.total().overdue == by_bill.total().overdue  # overdue is by due date
    for bill in by_bill.bills:
        assert bill.days == (on - bill.bill_date).days
    for bill in by_due.bills:
        assert bill.days == (on - bill.due).days


def test_each_bill_names_the_voucher_that_raised_it(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _synced(db, monkeypatch, FOLDER / "books")
    companies = [db.query(A.Entity).one().id]
    found = ageing(db, companies, date(2026, 10, 2), "customers", since=date(2026, 4, 1))
    assert found.bills
    for bill in found.bills:
        if bill.voucher_id is not None:
            assert db.get(A.Voucher, bill.voucher_id) is not None
    assert found.days_to_pay is None or found.days_to_pay >= 0
