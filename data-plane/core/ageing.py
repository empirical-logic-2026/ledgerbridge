"""Receivables and payables with ageing (RPT-004, RPT-014; docs/design/dashboard.md Section
0.4): every customer (vendor), known by name across the selected companies, with its balance
due at a day, its outstanding bills by how long they are past due, and what isn't in bills.
Source-independent; formulas F-PTY-013 to F-PTY-019 in docs/formula-sheet.md.

- **Bills:** as on the party's page (core/parties.py): per ledger and bill name, the opening
  bills and the allocations of effective vouchers up to the day ("on account" excluded), due
  on the bill's due date, else the bill's date plus the party's credit days; settled when
  less than half a paisa is left. Each open bill names the voucher that raised it (none for
  an opening bill).
- **Buckets** (F-PTY-014): not due, 1-30, 31-60, 61-90, 91-180 and over 180 days, counted
  from the due date (the default) or from the bill's date (`basis="bill_date"`). An advance
  or overpayment (a negative bill) counts where it falls. Overdue is always by the due date.
- **Foreign-currency parties:** where the source's revalued balance is stored for the day
  (`fx_revaluation_snapshots`, on statement dates), the balance is that one, as the source's
  Balance Sheet shows it; its bills stay at their book amounts.
- **Not in bills** (F-PTY-013): the balance due less the bills, in four parts: amounts on
  account (F-PTY-015), the ledgers' openings less their opening bills (F-PTY-016), the
  exchange-rate revaluation of foreign-currency parties (F-PTY-020), and the rest (F-PTY-017:
  entries without a bill, e.g. a ledger not kept bill by bill).
- **Average days to pay** (F-PTY-019): the bills settled in the period, the days from each
  bill's date to its settlement, weighted by the amount, over every party.

The balances add up to the party ledgers' closing balance at the day: the Sundry Debtors
(Sundry Creditors) line of the Balance Sheet when every debtor (creditor) ledger is a party
(proved against Tally: tests/test_ageing.py).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import accounting as A  # noqa: N812
from core.parties import KINDS, Kind, balances_by_name, opening_bill_rows

ZERO = Decimal(0)
HALF_PAISA = Decimal("0.005")
BUCKETS = ("not_due", "days_1_30", "days_31_60", "days_61_90", "days_91_180", "over_180")
OVER_90 = ("days_91_180", "over_180")
Basis = Literal["due_date", "bill_date"]


def bucket(days: int) -> str:
    """The bucket of a bill this many days past its due date (or its bill date); 0 or
    less: not due (F-PTY-014)."""
    if days <= 0:
        return "not_due"
    for limit, name in ((30, "days_1_30"), (60, "days_31_60"), (90, "days_61_90"),
                        (180, "days_91_180")):  # fmt: skip
        if days <= limit:
            return name
    return "over_180"


@dataclass
class OpenBill:
    """One outstanding bill at the day."""

    party_id: int
    party: str
    name: str  # the bill's reference
    bill_date: date
    due: date
    amount: Decimal  # positive when owed in the usual direction
    days: int  # by the basis: days past the due date, or since the bill's date
    overdue_days: int  # days past the due date (0 when not due)
    voucher_id: int | None  # the voucher that raised it; None for an opening bill


@dataclass
class AgeingRow:
    party_id: int  # one of the parties of that name (its page's id)
    name: str
    balance: Decimal  # due at the day, positive when owed in the usual direction
    buckets: dict[str, Decimal] = field(default_factory=lambda: dict.fromkeys(BUCKETS, ZERO))
    overdue: Decimal = ZERO
    pending: Decimal = ZERO
    advance: Decimal = ZERO
    on_account: Decimal = ZERO  # F-PTY-015
    opening_difference: Decimal = ZERO  # F-PTY-016
    revaluation: Decimal = ZERO  # F-PTY-020: the source's revalued balance less the book's

    @property
    def bills(self) -> Decimal:
        return sum(self.buckets.values(), ZERO)

    @property
    def uncovered(self) -> Decimal:
        """The balance not in bills (F-PTY-013)."""
        return self.balance - self.bills

    @property
    def other(self) -> Decimal:
        """Not in bills, neither on account, an opening difference nor a revaluation
        (F-PTY-017)."""
        return self.uncovered - self.on_account - self.opening_difference - self.revaluation

    @property
    def over_90(self) -> Decimal:
        """F-PTY-018."""
        return sum((self.buckets[b] for b in OVER_90), ZERO)

    def add(self, other: "AgeingRow") -> None:
        """Adds another row's figures (for the total)."""
        self.balance += other.balance
        self.overdue += other.overdue
        self.pending += other.pending
        self.advance += other.advance
        self.on_account += other.on_account
        self.opening_difference += other.opening_difference
        self.revaluation += other.revaluation
        for b in BUCKETS:
            self.buckets[b] += other.buckets[b]

    def add_outstanding(self, bill: OpenBill) -> None:
        self.buckets[bucket(bill.days)] += bill.amount
        if bill.amount > 0:
            if bill.overdue_days > 0:
                self.overdue += bill.amount
            else:
                self.pending += bill.amount
        elif bill.amount < 0:
            self.advance -= bill.amount


@dataclass
class Ageing:
    rows: list[AgeingRow]
    bills: list[OpenBill]
    days_to_pay: Decimal | None  # F-PTY-019

    def total(self) -> AgeingRow:
        total = AgeingRow(0, "Total", ZERO)
        for row in self.rows:
            total.add(row)
        return total


def ageing(
    session: Session,
    companies: list[int],
    on: date,
    kind: Kind,
    basis: Basis = "due_date",
    since: date | None = None,
) -> Ageing:
    """Every party of the kind with a balance or bills (the largest balance first), its open
    bills, and the average days to pay of the bills settled from `since` to `on`."""
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
    ledgers = _ledgers(session, [pid for pid, _, _ in parties])
    bills, days_to_pay = _bills(session, parties, ledgers, on, sign, basis, since)
    for bill in bills:
        rows[bill.party].add_outstanding(bill)
    for name, amount in _on_account(session, parties, ledgers, on, sign):
        rows[name].on_account += amount
    for name, amount in _opening_differences(session, parties, ledgers, sign):
        rows[name].opening_difference += amount
    for name, amount in _revaluations(session, parties, ledgers, on, sign):
        rows[name].revaluation += amount
        rows[name].balance += amount
    found = [r for r in rows.values() if r.balance != 0 or r.bills != 0]
    found.sort(key=lambda r: (-r.balance, r.name.lower()))
    for bill in bills:
        bill.party_id = rows[bill.party].party_id
    bills.sort(key=lambda b: (b.due, b.party.lower(), b.name))
    return Ageing(found, bills, days_to_pay)


def _ledgers(session: Session, party_ids: list[int]) -> dict[int, int]:
    """The parties' ledgers: ledger id -> party id."""
    if not party_ids:
        return {}
    return dict(
        session.execute(
            select(A.Ledger.id, A.Ledger.party_id).where(
                A.Ledger.party_id.in_(party_ids), A.Ledger.is_deleted.is_(False)
            )
        ).all()
    )


def _bills(
    session: Session,
    parties: list,
    ledgers: dict[int, int],
    on: date,
    sign: int,
    basis: Basis,
    since: date | None,
) -> tuple[list[OpenBill], Decimal | None]:
    """Every open bill at the day (F-PTY-004, aged by F-PTY-014), and the average days to
    pay of the bills settled from `since` (F-PTY-019)."""
    if not ledgers:
        return [], None
    credit = {pid: timedelta(days=days or 0) for pid, _, days in parties}
    names = {pid: name for pid, name, _ in parties}
    opening = [
        (ledger, name, kind, bill_on, due_on, day, None, amount)
        for ledger, name, kind, bill_on, due_on, day, _, _, amount in opening_bill_rows(
            session, list(ledgers)
        )
    ]
    vouchers = session.execute(
        select(
            A.VoucherLine.ledger_id, A.BillAllocation.bill_name, A.BillAllocation.bill_type,
            A.BillAllocation.bill_date, A.BillAllocation.due_date, A.Voucher.voucher_date,
            A.Voucher.id, A.BillAllocation.amount,
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
    ).all()  # fmt: skip
    amounts: dict[tuple[int, str], Decimal] = defaultdict(lambda: ZERO)
    dated: dict[tuple[int, str], date] = {}
    due: dict[tuple[int, str], date] = {}
    raised_by: dict[tuple[int, str], int | None] = {}
    weighted, settled = ZERO, ZERO
    for ledger, name, kind, bill_on, due_on, voucher_on, vid, amount in [*opening, *vouchers]:
        key = (ledger, name or "")
        day = bill_on or voucher_on
        if key not in dated:
            dated[key] = day
            due[key] = due_on or day + credit[ledgers[ledger]]
            raised_by[key] = vid
        if kind == "new_ref":
            if due_on:
                due[key] = due_on
            if vid is not None and raised_by[key] is None and amounts[key] == 0:
                raised_by[key] = vid
        elif kind == "against_ref" and since is not None and voucher_on >= since:
            size = abs(Decimal(amount))
            weighted += size * (voucher_on - dated[key]).days
            settled += size
        amounts[key] += sign * Decimal(amount)
    bills = []
    for key, amount in amounts.items():
        if abs(amount) < HALF_PAISA:
            continue
        ledger, name = key
        past_due = (on - due[key]).days
        days = past_due if basis == "due_date" else (on - dated[key]).days
        party = names[ledgers[ledger]]
        bills.append(
            OpenBill(ledgers[ledger], party, name, dated[key], due[key], amount, days,
                     max(past_due, 0), raised_by[key])
        )  # fmt: skip
    days_to_pay = (weighted / settled).quantize(Decimal("1")) if settled else None
    return bills, days_to_pay


def _on_account(
    session: Session, parties: list, ledgers: dict[int, int], on: date, sign: int
) -> list[tuple[str, Decimal]]:
    """Each party's allocations "on account" up to the day (F-PTY-015)."""
    if not ledgers:
        return []
    names = {pid: name for pid, name, _ in parties}
    rows = session.execute(
        select(A.VoucherLine.ledger_id, func.sum(A.BillAllocation.amount))
        .join(A.VoucherLine, A.VoucherLine.id == A.BillAllocation.voucher_line_id)
        .join(A.Voucher, A.Voucher.id == A.VoucherLine.voucher_id)
        .where(
            A.VoucherLine.ledger_id.in_(list(ledgers)),
            A.VoucherLine.is_effective.is_(True),
            A.Voucher.is_deleted.is_(False),
            A.BillAllocation.bill_type == "on_account",
            A.VoucherLine.voucher_date <= on,
        )
        .group_by(A.VoucherLine.ledger_id)
    )
    return [(names[ledgers[ledger]], sign * Decimal(total or 0)) for ledger, total in rows]


def _opening_differences(
    session: Session, parties: list, ledgers: dict[int, int], sign: int
) -> list[tuple[str, Decimal]]:
    """Each party's ledger openings less their opening bills (F-PTY-016): only for ledgers
    with opening bills, as a ledger without any isn't kept bill by bill (that is F-PTY-017)."""
    if not ledgers:
        return []
    names = {pid: name for pid, name, _ in parties}
    bills: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for ledger, total in session.execute(
        select(A.OpeningBill.ledger_id, func.sum(A.OpeningBill.amount))
        .where(A.OpeningBill.ledger_id.in_(list(ledgers)))
        .group_by(A.OpeningBill.ledger_id)
    ):
        bills[int(ledger)] = Decimal(total or 0)
    openings = session.execute(
        select(A.Ledger.id, A.Ledger.opening_balance).where(A.Ledger.id.in_(list(bills)))
    )
    return [
        (names[ledgers[ledger]], sign * (Decimal(opening or 0) - bills[ledger]))
        for ledger, opening in openings
    ]


def _revaluations(
    session: Session, parties: list, ledgers: dict[int, int], on: date, sign: int
) -> list[tuple[str, Decimal]]:
    """Each foreign-currency party's revalued balance less its book balance at the day, where
    the source's is stored (F-PTY-020)."""
    if not ledgers:
        return []
    names = {pid: name for pid, name, _ in parties}
    rows = session.execute(
        select(
            A.FxRevaluationSnapshot.ledger_id,
            A.FxRevaluationSnapshot.revalued_value - A.FxRevaluationSnapshot.book_value,
        ).where(
            A.FxRevaluationSnapshot.ledger_id.in_(list(ledgers)),
            A.FxRevaluationSnapshot.as_of == on,
        )
    )
    return [(names[ledgers[ledger]], sign * Decimal(diff or 0)) for ledger, diff in rows]
