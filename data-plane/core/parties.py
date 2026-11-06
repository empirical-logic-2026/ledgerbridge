"""Customers and vendors (D2; docs/design/dashboard.md Section 0.3, screen 8): the lists and
one party's page. Source-independent.

A party is known by its **name** across the selected companies (as the facets are): the same
customer in two companies is one row and one page, their figures added together. Its ledgers
are those linked to any of those parties.

- **Balance due** at the period's end: the ledgers' openings plus their effective entries up
  to that day (debit positive; a vendor's shown as a positive amount owed).
- **Sales (purchases):** core/sales.py with the party as the facet.
- **Receipts (payments):** what receipt (payment) vouchers put on the party's ledgers.
- **Ledger statement:** the opening at the period's start, every effective entry on the
  party's ledgers in the period with the other side's first ledger as Particulars, and the
  running balance.
- **Outstanding bills** at the period's end: the ledgers' opening bills (raised before the
  books' beginning) and the bill allocations of effective vouchers up to that day ("on
  account" excluded), added up per ledger and bill name; due on the bill's due date, else the
  bill's date plus the party's credit days. A balance not split into bills (e.g. "on account")
  isn't covered by them: `bills_cover` says how much they cover.
- **Average days to pay:** settlements ("against" allocations) in the period, the days from
  the bill's date, weighted by amount.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import accounting as A  # noqa: N812
from core.registers import Register, register
from core.report_periods import Period
from core.reporting_views import GROUP_ANCESTORS
from core.sales import (
    PURCHASES_SIDE,
    SALES_SIDE,
    Facets,
    Side,
    Totals,
    lines,
    monthly_totals,
    period_totals,
    split_columns,
    to_totals,
)

ZERO = Decimal(0)
HALF_PAISA = Decimal("0.005")
LIMIT = 20_000  # ledger statement entries
Kind = Literal["customers", "vendors"]
PaymentStatus = Literal["overdue", "pending", "advance", "settled", "no_bill", "mixed"]


def bill_payment_status(amount: Decimal, due: date, as_of: date) -> PaymentStatus:
    """Classify a bill's remaining allocation, not the original invoice amount."""
    if amount <= -HALF_PAISA:
        return "advance"
    if amount < HALF_PAISA:
        return "settled"
    return "overdue" if due < as_of else "pending"


def party_payment_status(
    balance: Decimal, overdue: Decimal, pending: Decimal, advance: Decimal = ZERO
) -> PaymentStatus:
    """Summarize bill states without hiding a mixture behind one overdue label."""
    if balance <= -HALF_PAISA:
        return "advance"
    if balance < HALF_PAISA:
        return "settled"
    if overdue > 0 and (pending > 0 or advance > 0):
        return "mixed"
    if pending > 0 and advance > 0:
        return "mixed"
    if overdue > 0:
        return "overdue"
    return "pending" if pending > 0 else "no_bill"


KINDS: dict[str, tuple[tuple[str, ...], Side, str, int]] = {
    # party types listed, side, the voucher base type that settles, sign of the balance shown
    "customers": (("customer", "both"), SALES_SIDE, "receipt", 1),
    "vendors": (("vendor", "both"), PURCHASES_SIDE, "payment", -1),
}


@dataclass
class PartyRef:
    id: int  # the party asked for
    name: str
    party_ids: list[int]
    companies: list[int]  # of the selected companies, where the party exists
    ledger_ids: list[int]
    group_path: list[str]  # the first ledger's groups, the top one first
    credit_days: int | None


@dataclass
class Bill:
    ledger_id: int
    name: str
    on: date  # the bill's date
    due: date
    amount: Decimal  # outstanding, shown positive when owed in the party's usual direction
    company: int


@dataclass
class Entry:
    voucher_id: int
    company: int
    on: date
    voucher_type: str
    number: str
    particulars: str
    amount: Decimal  # debit positive
    balance: Decimal = ZERO  # running, debit positive
    narration: str | None = None


@dataclass
class Settlement:
    voucher_id: int
    company: int
    on: date
    voucher_type: str
    number: str
    amount: Decimal  # received (paid), positive
    narration: str | None


@dataclass
class PartyPage:
    party: PartyRef
    balance: Decimal  # due at the end, positive when owed in the usual direction
    totals: Totals
    before: Totals | None  # the comparison period's
    settled: Decimal  # receipts (payments) in the period
    days_to_pay: Decimal | None
    bills: list[Bill]
    statement_opening: Decimal  # debit positive
    statement: list[Entry]
    statement_truncated: bool
    settlements: list[Settlement]
    invoices: Register
    monthly: list[tuple[date, Totals, Decimal]]  # month, side figures, settled
    main_channel: str | None
    as_of: date  # the period's end
    bills_by_voucher: dict[int, Bill] = field(default_factory=dict)  # an invoice's own bill

    @property
    def overdue(self) -> Decimal:
        return sum((b.amount for b in self.bills if b.amount > 0 and b.due < self.as_of), ZERO)

    @property
    def bills_cover(self) -> Decimal:
        return sum((b.amount for b in self.bills), ZERO)


@dataclass
class PartyRow:
    party_id: int  # one of the parties of that name (the page's id)
    name: str
    companies: list[int]
    balance: Decimal  # due at the end, positive when owed in the usual direction
    net: Decimal  # sales (purchases) in the period
    invoices: int
    last_invoice: date | None


# --- the list ----------------------------------------------------------------------------


def party_list(
    session: Session, companies: list[int], period: Period, kind: Kind
) -> list[PartyRow]:
    types, side, _, sign = KINDS[kind]
    parties = session.execute(
        select(A.Party.id, A.Party.name, A.Party.entity_id).where(
            A.Party.entity_id.in_(companies),
            A.Party.party_type.in_(types),
            A.Party.is_deleted.is_(False),
        )
    ).all()
    by_name: dict[str, PartyRow] = {}
    for pid, name, entity in parties:
        row = by_name.setdefault(name, PartyRow(pid, name, [], ZERO, ZERO, 0, None))
        row.party_id = min(row.party_id, pid)
        if entity not in row.companies:
            row.companies.append(entity)
    ids = [pid for pid, _, _ in parties]
    for name, total in balances_by_name(session, ids, period.end):
        if name in by_name:
            by_name[name].balance += sign * total
    query = lines(
        companies, period, Facets(), side, A.Party.name, *split_columns(side),
        func.max(A.Voucher.voucher_date),
    ).join(A.Party, A.Party.id == A.Voucher.party_id).group_by(A.Party.name)  # fmt: skip
    for name, gross, returns, other, invoices, last in session.execute(query):
        if name in by_name:
            totals = to_totals(side, gross, returns, other, invoices)
            by_name[name].net, by_name[name].invoices = totals.net, totals.invoices
            by_name[name].last_invoice = last
    return sorted(by_name.values(), key=lambda r: r.name.lower())


def balances_by_name(session: Session, party_ids: list[int], on: date) -> list[tuple[str, Decimal]]:
    """Each party name's ledgers: openings plus effective entries up to the day."""
    if not party_ids:
        return []
    ledgers = (
        select(A.Ledger.id, A.Party.name, A.Ledger.opening_balance)
        .join(A.Party, A.Party.id == A.Ledger.party_id)
        .where(A.Ledger.party_id.in_(party_ids), A.Ledger.is_deleted.is_(False))
    ).subquery()
    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for name, opening in session.execute(select(ledgers.c.name, ledgers.c.opening_balance)):
        totals[name] += Decimal(opening or 0)
    entries = (
        select(ledgers.c.name, func.sum(A.VoucherLine.amount))
        .join(ledgers, ledgers.c.id == A.VoucherLine.ledger_id)
        .join(A.Voucher, A.Voucher.id == A.VoucherLine.voucher_id)
        .where(
            A.VoucherLine.is_effective.is_(True),
            A.Voucher.is_deleted.is_(False),
            A.VoucherLine.voucher_date <= on,
        )
        .group_by(ledgers.c.name)
    )
    for name, total in session.execute(entries):
        totals[name] += Decimal(total or 0)
    return list(totals.items())


# --- one party ---------------------------------------------------------------------------


def find_party(session: Session, companies: list[int], party_id: int) -> PartyRef | None:
    """The party and the others of its name in the companies; None outside them."""
    party = session.get(A.Party, party_id)
    if party is None or party.entity_id not in companies or party.is_deleted:
        return None
    same = session.execute(
        select(A.Party.id, A.Party.entity_id).where(
            A.Party.entity_id.in_(companies),
            A.Party.name == party.name,
            A.Party.is_deleted.is_(False),
        )
    ).all()
    ids = [pid for pid, _ in same]
    ledgers = list(
        session.scalars(
            select(A.Ledger.id)
            .where(A.Ledger.party_id.in_(ids), A.Ledger.is_deleted.is_(False))
            .order_by(A.Ledger.id)
        )
    )
    return PartyRef(
        id=party.id,
        name=party.name,
        party_ids=ids,
        companies=sorted({entity for _, entity in same}),
        ledger_ids=ledgers,
        group_path=_group_path(session, ledgers[0]) if ledgers else [],
        credit_days=party.credit_days,
    )


def _group_path(session: Session, ledger_id: int) -> list[str]:
    """The ledger's group and its parents' names, the top one first."""
    group_id = session.scalar(select(A.Ledger.group_id).where(A.Ledger.id == ledger_id))
    rows = session.execute(
        select(A.AccountGroup.name, GROUP_ANCESTORS.c.depth)
        .join(GROUP_ANCESTORS, GROUP_ANCESTORS.c.ancestor_id == A.AccountGroup.id)
        .where(GROUP_ANCESTORS.c.group_id == group_id)
        .order_by(GROUP_ANCESTORS.c.depth.desc())
    ).all()
    return [name for name, _ in rows]


def party_page(
    session: Session, companies: list[int], party: PartyRef, period: Period, kind: Kind,
    before: Period | None,
) -> PartyPage:  # fmt: skip
    _, side, settles, sign = KINDS[kind]
    facets = Facets(parties=(party.name,))
    chosen = [c for c in companies if c in party.companies]
    opening = _balance(session, party.ledger_ids, period.start - timedelta(days=1))
    statement, truncated = _statement(session, party, period, opening)
    closing = statement[-1].balance if statement else opening
    if truncated:
        closing = _balance(session, party.ledger_ids, period.end)
    settlements = _settlements(session, party, period, settles, sign)
    bills, by_voucher = _bills(session, party, period.end, sign)
    return PartyPage(
        party=party,
        balance=sign * closing,
        totals=period_totals(session, chosen, period, facets, side),
        before=period_totals(session, chosen, before, facets, side) if before else None,
        settled=sum((s.amount for s in settlements), ZERO),
        days_to_pay=_days_to_pay(session, party, period),
        bills=bills,
        statement_opening=opening,
        statement=statement,
        statement_truncated=truncated,
        settlements=settlements,
        invoices=register(session, chosen, period, side, facets),
        monthly=_with_settled(monthly_totals(session, chosen, period, facets, side), settlements),
        main_channel=_main_channel(session, chosen, period, facets, side),
        as_of=period.end,
        bills_by_voucher=by_voucher,
    )


def due_and_overdue(
    session: Session, party: PartyRef, on: date, sign: int
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """The normalized balance and overdue, pending and advance bill amounts."""
    bills, _ = _bills(session, party, on, sign)
    overdue = sum((b.amount for b in bills if b.amount > 0 and b.due < on), ZERO)
    pending = sum((b.amount for b in bills if b.amount > 0 and b.due >= on), ZERO)
    advance = sum((-b.amount for b in bills if b.amount < 0), ZERO)
    return sign * _balance(session, party.ledger_ids, on), overdue, pending, advance


def _balance(session: Session, ledger_ids: list[int], on: date) -> Decimal:
    if not ledger_ids:
        return ZERO
    opening = session.scalar(
        select(func.coalesce(func.sum(A.Ledger.opening_balance), 0)).where(
            A.Ledger.id.in_(ledger_ids)
        )
    )
    entries = session.scalar(
        select(func.coalesce(func.sum(A.VoucherLine.amount), 0))
        .join(A.Voucher, A.Voucher.id == A.VoucherLine.voucher_id)
        .where(
            A.VoucherLine.ledger_id.in_(ledger_ids),
            A.VoucherLine.is_effective.is_(True),
            A.Voucher.is_deleted.is_(False),
            A.VoucherLine.voucher_date <= on,
        )
    )
    return Decimal(opening or 0) + Decimal(entries or 0)


def _statement(
    session: Session, party: PartyRef, period: Period, opening: Decimal
) -> tuple[list[Entry], bool]:
    """The party's entries in the period, the earliest first, with the running balance."""
    if not party.ledger_ids:
        return [], False
    query = (
        select(
            A.Voucher.id, A.Voucher.entity_id, A.Voucher.voucher_date, A.VoucherType.name,
            A.Voucher.voucher_number, func.sum(A.VoucherLine.amount), A.Voucher.narration,
        )
        .join(A.Voucher, A.Voucher.id == A.VoucherLine.voucher_id)
        .join(A.VoucherType, A.VoucherType.id == A.Voucher.voucher_type_id)
        .where(
            A.VoucherLine.ledger_id.in_(party.ledger_ids),
            A.VoucherLine.is_effective.is_(True),
            A.Voucher.is_deleted.is_(False),
            A.VoucherLine.voucher_date >= period.start,
            A.VoucherLine.voucher_date <= period.end,
        )
        .group_by(
            A.Voucher.id, A.Voucher.entity_id, A.Voucher.voucher_date, A.VoucherType.name,
            A.Voucher.voucher_number, A.Voucher.narration,
        )
        .order_by(A.Voucher.voucher_date, A.Voucher.id)
        .limit(LIMIT + 1)
    )  # fmt: skip
    rows = session.execute(query).all()
    truncated = len(rows) > LIMIT
    rows = rows[:LIMIT]
    other = _other_sides(session, [r[0] for r in rows], party.ledger_ids)
    entries, running = [], opening
    for vid, entity, on, vtype, number, amount, narration in rows:
        running += Decimal(amount)
        entries.append(
            Entry(vid, entity, on, vtype, number, other.get(vid, ""), Decimal(amount), running,
                  narration)
        )  # fmt: skip
    return entries, truncated


def _other_sides(session: Session, voucher_ids: list[int], ledger_ids: list[int]) -> dict[int, str]:
    """Each voucher's first ledger not of the party: the statement's Particulars."""
    found: dict[int, str] = {}
    for start in range(0, len(voucher_ids), 1000):
        chunk = voucher_ids[start : start + 1000]
        rows = session.execute(
            select(A.VoucherLine.voucher_id, A.Ledger.name)
            .join(A.Ledger, A.Ledger.id == A.VoucherLine.ledger_id)
            .where(A.VoucherLine.voucher_id.in_(chunk), A.VoucherLine.ledger_id.not_in(ledger_ids))
            .order_by(A.VoucherLine.voucher_id, A.VoucherLine.line_no)
        )
        for vid, name in rows:
            found.setdefault(vid, name)
    return found


def _settlements(
    session: Session, party: PartyRef, period: Period, base: str, sign: int
) -> list[Settlement]:
    """Receipts (payments) on the party's ledgers in the period."""
    if not party.ledger_ids:
        return []
    query = (
        select(
            A.Voucher.id, A.Voucher.entity_id, A.Voucher.voucher_date, A.VoucherType.name,
            A.Voucher.voucher_number, func.sum(A.VoucherLine.amount), A.Voucher.narration,
        )
        .join(A.Voucher, A.Voucher.id == A.VoucherLine.voucher_id)
        .join(A.VoucherType, A.VoucherType.id == A.Voucher.voucher_type_id)
        .where(
            A.VoucherLine.ledger_id.in_(party.ledger_ids),
            A.VoucherLine.is_effective.is_(True),
            A.Voucher.is_deleted.is_(False),
            A.VoucherType.base_type == base,
            A.VoucherLine.voucher_date >= period.start,
            A.VoucherLine.voucher_date <= period.end,
        )
        .group_by(
            A.Voucher.id, A.Voucher.entity_id, A.Voucher.voucher_date, A.VoucherType.name,
            A.Voucher.voucher_number, A.Voucher.narration,
        )
        .order_by(A.Voucher.voucher_date, A.Voucher.id)
    )  # fmt: skip
    # A receipt credits the customer (negative); a payment debits the vendor (positive).
    return [
        Settlement(vid, entity, on, vtype, number, -sign * Decimal(amount), narration)
        for vid, entity, on, vtype, number, amount, narration in session.execute(query)
    ]


def opening_bill_rows(session: Session, ledger_ids: list[int]) -> list[tuple]:
    """The ledgers' opening bills as bill rows, new bills raised before the books' beginning:
    (ledger, name, "new_ref", bill date, due date, the bill's date or else the books'
    beginning, no voucher, entity, amount)."""
    if not ledger_ids:
        return []
    rows = session.execute(
        select(
            A.OpeningBill.ledger_id, A.OpeningBill.bill_name, A.OpeningBill.bill_date,
            A.OpeningBill.due_date, A.Entity.books_from, A.OpeningBill.entity_id,
            A.OpeningBill.amount,
        )
        .join(A.Entity, A.Entity.id == A.OpeningBill.entity_id)
        .where(A.OpeningBill.ledger_id.in_(ledger_ids))
        .order_by(A.OpeningBill.id)
    )  # fmt: skip
    return [
        (ledger, name, "new_ref", bill_on, due, bill_on or books_from or date.min, None, entity,
         amount)
        for ledger, name, bill_on, due, books_from, entity, amount in rows
    ]  # fmt: skip


def _bill_rows(session: Session, party: PartyRef, on: date) -> list[tuple]:
    """Every bill row of the party's ledgers up to the day: opening bills first."""
    if not party.ledger_ids:
        return []
    return [*opening_bill_rows(session, party.ledger_ids), *_voucher_bill_rows(session, party, on)]


def _voucher_bill_rows(session: Session, party: PartyRef, on: date) -> list[tuple]:
    return session.execute(
        select(
            A.VoucherLine.ledger_id, A.BillAllocation.bill_name, A.BillAllocation.bill_type,
            A.BillAllocation.bill_date, A.BillAllocation.due_date, A.Voucher.voucher_date,
            A.Voucher.id, A.Voucher.entity_id, A.BillAllocation.amount,
        )
        .join(A.VoucherLine, A.VoucherLine.id == A.BillAllocation.voucher_line_id)
        .join(A.Voucher, A.Voucher.id == A.VoucherLine.voucher_id)
        .where(
            A.VoucherLine.ledger_id.in_(party.ledger_ids),
            A.VoucherLine.is_effective.is_(True),
            A.Voucher.is_deleted.is_(False),
            A.BillAllocation.bill_type != "on_account",
            A.VoucherLine.voucher_date <= on,
        )
        .order_by(A.Voucher.voucher_date, A.Voucher.id)
    ).all()  # fmt: skip


def _bills(
    session: Session, party: PartyRef, on: date, sign: int
) -> tuple[list[Bill], dict[int, Bill]]:
    """Outstanding bills at the day, and the bill each voucher raised (its first new one)."""
    credit = timedelta(days=party.credit_days or 0)
    bills: dict[tuple[int, str], Bill] = {}
    raised: dict[int, tuple[int, str]] = {}
    for ledger, name, kind, bill_on, due, voucher_on, vid, entity, amount in _bill_rows(
        session, party, on
    ):
        key = (ledger, name or "")
        day = bill_on or voucher_on
        bill = bills.get(key)
        if bill is None:
            bill = bills[key] = Bill(ledger, name or "", day, due or day + credit, ZERO, entity)
        if kind == "new_ref":
            if vid is not None:  # an opening bill has no voucher
                raised.setdefault(vid, key)
            if due:
                bill.due = due
        bill.amount += sign * Decimal(amount)
    outstanding = [b for b in bills.values() if abs(b.amount) >= HALF_PAISA]
    by_voucher = {vid: bills[key] for vid, key in raised.items()}
    return sorted(outstanding, key=lambda b: (b.due, b.name)), by_voucher


def _days_to_pay(session: Session, party: PartyRef, period: Period) -> Decimal | None:
    """Settlements in the period: the days from the bill's date, weighted by amount."""
    dates: dict[tuple[int, str], date] = {}
    weighted, total = ZERO, ZERO
    for ledger, name, kind, bill_on, _, voucher_on, _, _, amount in _bill_rows(
        session, party, period.end
    ):
        key = (ledger, name or "")
        if kind == "new_ref":
            dates.setdefault(key, bill_on or voucher_on)
        elif kind == "against_ref" and voucher_on >= period.start and key in dates:
            size = abs(Decimal(amount))
            weighted += size * (voucher_on - dates[key]).days
            total += size
    if not total:
        return None
    return (weighted / total).quantize(Decimal("1"))


def _with_settled(
    monthly: list[tuple[date, Totals]], settlements: list[Settlement]
) -> list[tuple[date, Totals, Decimal]]:
    settled: dict[date, Decimal] = defaultdict(lambda: ZERO)
    for s in settlements:
        settled[s.on.replace(day=1)] += s.amount
    return [(m, t, settled[m]) for m, t in monthly]


def _main_channel(
    session: Session, companies: list[int], period: Period, facets: Facets, side: Side
) -> str | None:
    """The voucher type with the most net sales (purchases) in the period."""
    query = (
        lines(companies, period, facets, side, A.VoucherType.name, func.sum(A.VoucherLine.amount))
        .group_by(A.VoucherType.name)
        .order_by(func.sum(A.VoucherLine.amount) * side.sign * -1, A.VoucherType.name)
        .limit(1)
    )
    row = session.execute(query).first()
    return row[0] if row else None
