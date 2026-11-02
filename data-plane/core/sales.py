"""The Sales dashboard's figures (D2; RPT-013, docs/design/dashboard.md Section 0.2, screen 7)
for any combination of companies, a period (core/report_periods.py) and the facets (customer
and channel names). Written for both sides, sales and purchases, so the Purchases pages use
the same definitions.

Source-independent, and the same definition as the monthly sales views (migration 0021,
proven against the source's statements): the effective entries of vouchers not deleted on
the ledgers under the side's predefined group (Sales Accounts, Purchase Accounts) at any
depth, split by the voucher's base type:

- **gross:** on invoices (base type sales, or purchase);
- **returns:** on the notes (credit notes for sales, debit notes for purchases);
- **other adjustments:** on any other voucher (journals and the like);
- **net** = gross + returns + other. Sales are positive (credits), purchases positive (debits);
  returns are therefore negative.

**Invoices** are the invoice vouchers with an entry on those ledgers; the **average invoice**
is gross divided by them. **Customers** (vendors) are the voucher's party; vouchers without
one are counted as "no party". Several companies are added together: combined, without
inter-company eliminations.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from core.home import PURCHASES, SALES, in_period, ledgers_under
from core.models import accounting as A  # noqa: N812
from core.report_periods import Period

ZERO = Decimal(0)
TOP = 10  # top customers, largest invoices


@dataclass(frozen=True)
class Side:
    roles: tuple[str, ...]  # the predefined groups whose ledgers count
    invoice: str  # the invoices' base type
    note: str  # the returns' base type
    sign: int  # turns the canonical amount (debit +) into the side's positive figure


SALES_SIDE = Side((SALES,), "sales", "credit_note", -1)
PURCHASES_SIDE = Side((PURCHASES,), "purchase", "debit_note", 1)


@dataclass(frozen=True)
class Facets:
    """Names chosen in the top filter bar; empty: all."""

    parties: tuple[str, ...] = ()
    voucher_types: tuple[str, ...] = ()


@dataclass
class Totals:
    gross: Decimal = ZERO
    returns: Decimal = ZERO
    other: Decimal = ZERO
    invoices: int = 0

    @property
    def net(self) -> Decimal:
        return self.gross + self.returns + self.other

    @property
    def average_invoice(self) -> Decimal | None:
        if not self.invoices:
            return None
        return (self.gross / self.invoices).quantize(Decimal("0.01"), ROUND_HALF_UP)


@dataclass
class PartyFigures:
    company: int
    party_id: int | None  # None: vouchers without a party
    name: str | None
    net: Decimal
    invoices: int


@dataclass
class Invoice:
    voucher_id: int
    company: int
    on: date
    number: str
    voucher_type: str
    party_id: int | None
    party: str | None
    amount: Decimal  # the invoice's entries on the side's ledgers


@dataclass
class Dashboard:
    period: Period
    totals: Totals
    last_year: Totals | None
    monthly: list[tuple[date, Totals]]
    top_parties: list[PartyFigures]
    other_parties: Decimal  # the net of the parties after the top ones (and of "no party")
    parties: int  # how many parties had entries
    largest: list[Invoice] = field(default_factory=list)


def dashboard(
    session: Session,
    companies: list[int],
    period: Period,
    compare: bool,
    facets: Facets = Facets(),  # noqa: B008
    side: Side = SALES_SIDE,
) -> Dashboard:
    totals = period_totals(session, companies, period, facets, side)
    last_year = (
        period_totals(session, companies, period.last_year(), facets, side) if compare else None
    )
    tops, others, count = _parties(session, companies, period, facets, side)
    return Dashboard(
        period=period,
        totals=totals,
        last_year=last_year,
        monthly=monthly_totals(session, companies, period, facets, side),
        top_parties=tops,
        other_parties=others,
        parties=count,
        largest=_largest(session, companies, period, facets, side),
    )


def lines(companies: list[int], period: Period, facets: Facets, side: Side, *columns: Any):  # noqa: ANN201
    """The side's effective entries in the period, with the facets applied, selecting
    `columns` (VoucherLine, Voucher and VoucherType joined)."""
    query = (
        select(*columns)
        .select_from(A.VoucherLine)
        .join(A.Voucher, A.Voucher.id == A.VoucherLine.voucher_id)
        .join(A.VoucherType, A.VoucherType.id == A.Voucher.voucher_type_id)
        .where(
            A.VoucherLine.entity_id.in_(companies),
            A.VoucherLine.is_effective.is_(True),
            A.Voucher.is_deleted.is_(False),
            A.VoucherLine.ledger_id.in_(ledgers_under(companies, side.roles)),
        )
    )
    if facets.parties:
        named = select(A.Party.id).where(
            A.Party.entity_id.in_(companies), A.Party.name.in_(facets.parties)
        )
        query = query.where(A.Voucher.party_id.in_(named))
    if facets.voucher_types:
        query = query.where(A.VoucherType.name.in_(facets.voucher_types))
    return in_period(query, period)


def split_columns(side: Side) -> list[Any]:
    """Gross, returns, other (canonical sign) and the invoices, as SQL columns."""
    amount, base = A.VoucherLine.amount, A.VoucherType.base_type
    return [
        func.coalesce(func.sum(case((base == side.invoice, amount), else_=0)), 0),
        func.coalesce(func.sum(case((base == side.note, amount), else_=0)), 0),
        func.coalesce(func.sum(case((base.in_((side.invoice, side.note)), 0), else_=amount)), 0),
        func.count(func.distinct(case((base == side.invoice, A.Voucher.id)))),
    ]


def to_totals(side: Side, gross: Any, returns: Any, other: Any, invoices: Any) -> Totals:
    def signed(value: Any) -> Decimal:
        return side.sign * Decimal(value or 0)

    return Totals(signed(gross), signed(returns), signed(other), int(invoices or 0))


def period_totals(
    session: Session, companies: list[int], period: Period, facets: Facets, side: Side
) -> Totals:
    row = session.execute(lines(companies, period, facets, side, *split_columns(side))).one()
    return to_totals(side, *row)


def monthly_totals(
    session: Session, companies: list[int], period: Period, facets: Facets, side: Side
) -> list[tuple[date, Totals]]:
    year, month = func.year(A.VoucherLine.voucher_date), func.month(A.VoucherLine.voucher_date)
    query = lines(companies, period, facets, side, *split_columns(side), year, month).group_by(
        year, month
    )
    found = {m: Totals() for m in period.month_starts()}
    for gross, returns, other, invoices, y, m in session.execute(query):
        found[date(int(y), int(m), 1)] = to_totals(side, gross, returns, other, invoices)
    return sorted(found.items())


def _parties(
    session: Session, companies: list[int], period: Period, facets: Facets, side: Side
) -> tuple[list[PartyFigures], Decimal, int]:
    """The parties with the largest net, the net of the rest, and how many there were."""
    query = (
        lines(
            companies, period, facets, side,
            A.Voucher.entity_id, A.Voucher.party_id, A.Party.name, *split_columns(side),
        )
        .outerjoin(A.Party, A.Party.id == A.Voucher.party_id)
        .group_by(A.Voucher.entity_id, A.Voucher.party_id, A.Party.name)
    )  # fmt: skip
    found = []
    for entity, party, name, *split in session.execute(query):
        totals = to_totals(side, *split)
        found.append(PartyFigures(int(entity), party, name, totals.net, totals.invoices))
    named = sorted((p for p in found if p.party_id is not None), key=lambda p: p.net, reverse=True)
    top = named[:TOP]
    total = sum((p.net for p in found), ZERO)
    return top, total - sum((p.net for p in top), ZERO), len(named)


def _largest(
    session: Session, companies: list[int], period: Period, facets: Facets, side: Side
) -> list[Invoice]:
    total = func.sum(A.VoucherLine.amount) * side.sign
    query = (
        lines(
            companies, period, facets, side,
            A.Voucher.id, A.Voucher.entity_id, A.Voucher.voucher_date, A.Voucher.voucher_number,
            A.VoucherType.name, A.Voucher.party_id, A.Party.name, total,
        )
        .outerjoin(A.Party, A.Party.id == A.Voucher.party_id)
        .where(A.VoucherType.base_type == side.invoice)
        .group_by(
            A.Voucher.id, A.Voucher.entity_id, A.Voucher.voucher_date, A.Voucher.voucher_number,
            A.VoucherType.name, A.Voucher.party_id, A.Party.name,
        )
        .order_by(total.desc(), A.Voucher.id)
        .limit(TOP)
    )  # fmt: skip
    return [
        Invoice(int(vid), int(entity), on, number, vtype, party_id, party, Decimal(amount or 0))
        for vid, entity, on, number, vtype, party_id, party, amount in session.execute(query)
    ]


# --- monthly figures with the closing balance, and by channel -------------------------------


def fy_start(day: date, start_month: int) -> date:
    """The first day of the financial year the day falls in."""
    return date(day.year if day.month >= start_month else day.year - 1, start_month, 1)


def monthly_with_closing(
    session: Session,
    companies: list[int],
    period: Period,
    facets: Facets = Facets(),  # noqa: B008
    side: Side = SALES_SIDE,
) -> list[tuple[date, Totals, Decimal]]:
    """Each month of the period with its figures and its closing balance: the net from the
    start of that month's financial year to its end, as the source's monthly summary of the
    group shows it (each company its own financial year; added up)."""
    closing: dict[date, Decimal] = defaultdict(lambda: ZERO)
    starts = {
        entity: start_month
        for entity, start_month in session.execute(
            select(A.Entity.id, A.Entity.fy_start_month).where(A.Entity.id.in_(companies))
        )
    }
    for company in companies:
        start_month = int(starts.get(company) or 4)
        whole = Period(fy_start(period.start, start_month), period.end)
        running = ZERO
        for month, totals in monthly_totals(session, [company], whole, facets, side):
            if month.month == start_month:
                running = ZERO
            running += totals.net
            closing[month] += running
    return [(m, t, closing[m]) for m, t in monthly_totals(session, companies, period, facets, side)]


@dataclass
class ChannelFigures:
    name: str  # the voucher type's name (types of the same name in several companies together)
    months: dict[date, Decimal]  # net per month
    totals: Totals


def by_channel(
    session: Session,
    companies: list[int],
    period: Period,
    facets: Facets = Facets(),  # noqa: B008
    side: Side = SALES_SIDE,
) -> list[ChannelFigures]:
    """Each voucher type's figures and net per month, the largest net first."""
    year, month = func.year(A.VoucherLine.voucher_date), func.month(A.VoucherLine.voucher_date)
    query = lines(
        companies, period, facets, side, A.VoucherType.name, year, month, *split_columns(side)
    ).group_by(A.VoucherType.name, year, month)
    found: dict[str, ChannelFigures] = {}
    for name, y, m, *split in session.execute(query):
        figures = found.setdefault(name, ChannelFigures(name, {}, Totals()))
        totals = to_totals(side, *split)
        figures.months[date(int(y), int(m), 1)] = totals.net
        figures.totals.gross += totals.gross
        figures.totals.returns += totals.returns
        figures.totals.other += totals.other
        figures.totals.invoices += totals.invoices
    return sorted(found.values(), key=lambda c: c.totals.net, reverse=True)
