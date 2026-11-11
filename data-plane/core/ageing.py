"""Receivables and payables with ageing (RPT-004, RPT-014; docs/design/dashboard.md Section
0.4): every customer (vendor), known by name across the selected companies, with its balance
due at a day and its outstanding bills by how long past due they are. Source-independent;
formulas F-PTY-012 and F-PTY-013 in docs/formula-sheet.md.

- **Bills:** as on the party's page (core/parties.py): per ledger and bill name, the opening
  bills and the allocations of effective vouchers up to the day ("on account" excluded), due
  on the bill's due date, else the bill's date plus the party's credit days; settled when
  less than half a paisa is left.
- **Buckets** (F-PTY-012), by the days from the due date to the day: not due, 1-30, 31-60,
  61-90 and over 90 days. An advance or overpayment (a negative bill) counts where it falls.
- **Uncovered** (F-PTY-013): the balance due less the bills: what isn't split into bills
  (e.g. "on account", or a ledger not kept bill by bill).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import accounting as A  # noqa: N812
from core.parties import KINDS, Kind, balances_by_name, opening_bill_rows

ZERO = Decimal(0)
HALF_PAISA = Decimal("0.005")
BUCKETS = ("not_due", "days_1_30", "days_31_60", "days_61_90", "over_90")


def bucket(days_past_due: int) -> str:
    """The bucket of a bill this many days past its due date (0 or less: not due)."""
    if days_past_due <= 0:
        return "not_due"
    if days_past_due <= 30:
        return "days_1_30"
    if days_past_due <= 60:
        return "days_31_60"
    if days_past_due <= 90:
        return "days_61_90"
    return "over_90"


@dataclass
class AgeingRow:
    party_id: int  # one of the parties of that name (its page's id)
    name: str
    balance: Decimal  # due at the day, positive when owed in the usual direction
    buckets: dict[str, Decimal] = field(default_factory=lambda: dict.fromkeys(BUCKETS, ZERO))
    overdue: Decimal = ZERO
    pending: Decimal = ZERO
    advance: Decimal = ZERO

    @property
    def bills(self) -> Decimal:
        return sum(self.buckets.values(), ZERO)

    @property
    def uncovered(self) -> Decimal:
        return self.balance - self.bills

    def add_outstanding(self, amount: Decimal, days_past_due: int) -> None:
        self.buckets[bucket(days_past_due)] += amount
        if amount > 0:
            if days_past_due > 0:
                self.overdue += amount
            else:
                self.pending += amount
        elif amount < 0:
            self.advance -= amount


def ageing(session: Session, companies: list[int], on: date, kind: Kind) -> list[AgeingRow]:
    """Every party of the kind with a balance or bills, the largest balance first."""
    types, _, _, sign = KINDS[kind]
    parties = session.execute(
        select(A.Party.id, A.Party.name, A.Party.credit_days).where(
            A.Party.entity_id.in_(companies),
            A.Party.party_type.in_(types),
            A.Party.is_deleted.is_(False),
        )
    ).all()
    rows: dict[str, AgeingRow] = {}
    for pid, name, _ in parties:
        row = rows.setdefault(name, AgeingRow(pid, name, ZERO))
        row.party_id = min(row.party_id, pid)
    for name, total in balances_by_name(session, [pid for pid, _, _ in parties], on):
        rows[name].balance = sign * total
    for name, amount, days in _outstanding(session, parties, on, sign):
        rows[name].add_outstanding(amount, days)
    found = [r for r in rows.values() if r.balance != 0 or r.bills != 0]
    return sorted(found, key=lambda r: (-r.balance, r.name.lower()))


def _outstanding(
    session: Session, parties: list, on: date, sign: int
) -> list[tuple[str, Decimal, int]]:
    """(party name, outstanding amount, days past due) of every open bill at the day."""
    credit = {pid: timedelta(days=days or 0) for pid, _, days in parties}
    names = {pid: name for pid, name, _ in parties}
    ledgers = dict(
        session.execute(
            select(A.Ledger.id, A.Ledger.party_id).where(
                A.Ledger.party_id.in_(list(names)), A.Ledger.is_deleted.is_(False)
            )
        ).all()
    )
    if not ledgers:
        return []
    opening = [
        (ledger, name, kind, bill_on, due_on, day, amount)
        for ledger, name, kind, bill_on, due_on, day, _, _, amount in opening_bill_rows(
            session, list(ledgers)
        )
    ]
    vouchers = session.execute(
        select(
            A.VoucherLine.ledger_id, A.BillAllocation.bill_name, A.BillAllocation.bill_type,
            A.BillAllocation.bill_date, A.BillAllocation.due_date, A.Voucher.voucher_date,
            A.BillAllocation.amount,
        )
        .join(A.VoucherLine, A.VoucherLine.id == A.BillAllocation.voucher_line_id)
        .join(A.Voucher, A.Voucher.id == A.VoucherLine.voucher_id)
        .where(
            A.VoucherLine.ledger_id.in_(list(ledgers)),
            A.VoucherLine.is_effective.is_(True),
            A.Voucher.is_deleted.is_(False),
            A.BillAllocation.bill_type != "on_account",
            A.VoucherLine.voucher_date <= on,
        )
        .order_by(A.Voucher.voucher_date, A.Voucher.id)
    )  # fmt: skip
    amounts: dict[tuple[int, str], Decimal] = defaultdict(lambda: ZERO)
    due: dict[tuple[int, str], date] = {}
    for ledger, name, kind, bill_on, due_on, voucher_on, amount in [*opening, *vouchers]:
        key = (ledger, name or "")
        day = bill_on or voucher_on
        if key not in due:
            due[key] = due_on or day + credit[ledgers[ledger]]
        if kind == "new_ref" and due_on:
            due[key] = due_on
        amounts[key] += sign * Decimal(amount)
    return [
        (names[ledgers[ledger]], amount, (on - due[(ledger, bill)]).days)
        for (ledger, bill), amount in amounts.items()
        if abs(amount) >= HALF_PAISA
    ]
