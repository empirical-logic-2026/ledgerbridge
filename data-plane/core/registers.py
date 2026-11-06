"""The Sales and Purchase registers (D2; docs/design/dashboard.md Section 0.2), in the Day Book
style of the source: one row per voucher with its date, particulars, voucher type and number,
debit or credit, and narration. Source-independent.

- **Which vouchers:** those whose base type is the side's invoice or note (sales and credit
  notes; purchases and debit notes), not deleted, posting to the books (`is_effective`: not
  cancelled, not optional), in the period, with the facets applied (party and voucher type
  names).
- **Particulars and amount:** the voucher's first ledger entry, as the source's Day Book shows
  it (for an invoice, the party); its amount is the debit or the credit column.
- **Side value:** the voucher's entries on the side's ledgers (Sales Accounts or Purchase
  Accounts, by predefined role, at any depth), positive as core/sales.py has them: the
  register's total of it is the gross plus returns of the monthly sales views.

- **Reference and instrument:** the voucher's reference (e.g. a supplier's invoice number) and
  its bank lines' cheque or transfer number and UTR.

At most `limit` vouchers, the earliest first; `truncated` says when there were more.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.home import in_period, ledgers_under
from core.models import accounting as A  # noqa: N812
from core.report_periods import Period
from core.sales import Facets, Side

LIMIT = 20_000


@dataclass
class RegisterRow:
    voucher_id: int
    company: int
    on: date
    voucher_type: str
    base_type: str
    number: str
    ledger_id: int
    particulars: str  # the first ledger entry's ledger
    party_id: int | None
    party: str | None
    amount: Decimal  # the first entry's: debit positive, credit negative
    side_value: Decimal  # on the side's ledgers, positive for invoices
    narration: str | None
    reference: str | None = None
    instrument_number: str | None = None  # a bank line's cheque or transfer number
    utr: str | None = None  # a bank line's UTR


@dataclass
class Register:
    rows: list[RegisterRow]
    truncated: bool


def register(
    session: Session,
    companies: list[int],
    period: Period,
    side: Side,
    facets: Facets = Facets(),  # noqa: B008
    limit: int = LIMIT,
) -> Register:
    first = _first_entries(companies, period)
    values = _side_values(companies, period, side)
    instruments = _instruments(companies, period)
    query = (
        select(
            A.Voucher.id, A.Voucher.entity_id, A.Voucher.voucher_date, A.VoucherType.name,
            A.VoucherType.base_type, A.Voucher.voucher_number, A.Ledger.id, A.Ledger.name,
            A.Voucher.party_id, A.Party.name, first.c.amount,
            func.coalesce(values.c.value, 0), A.Voucher.narration, A.Voucher.reference_number,
            instruments.c.instrument_number, instruments.c.utr,
        )
        .join(first, first.c.voucher_id == A.Voucher.id)
        .join(A.VoucherType, A.VoucherType.id == A.Voucher.voucher_type_id)
        .join(A.Ledger, A.Ledger.id == first.c.ledger_id)
        .outerjoin(A.Party, A.Party.id == A.Voucher.party_id)
        .outerjoin(values, values.c.voucher_id == A.Voucher.id)
        .outerjoin(instruments, instruments.c.voucher_id == A.Voucher.id)
        .where(
            first.c.n == 1,
            A.Voucher.is_deleted.is_(False),
            A.VoucherType.base_type.in_((side.invoice, side.note)),
        )
        .order_by(A.Voucher.voucher_date, A.Voucher.entity_id, A.Voucher.id)
        .limit(limit + 1)
    )  # fmt: skip
    if facets.parties:
        query = query.where(A.Party.name.in_(facets.parties))
    if facets.voucher_types:
        query = query.where(A.VoucherType.name.in_(facets.voucher_types))
    rows = [
        RegisterRow(
            int(vid), int(entity), on, vtype, base, number, int(ledger), ledger_name,
            party_id, party, Decimal(amount), side.sign * Decimal(value), narration, reference,
            instrument, utr,
        )
        for vid, entity, on, vtype, base, number, ledger, ledger_name, party_id, party, amount,
        value, narration, reference, instrument, utr in session.execute(query)
    ]  # fmt: skip
    return Register(rows[:limit], len(rows) > limit)


def _first_entries(companies: list[int], period: Period):  # noqa: ANN202
    """Each voucher's effective entries numbered in the source's order (n = 1: the first)."""
    numbered = select(
        A.VoucherLine.voucher_id,
        A.VoucherLine.ledger_id,
        A.VoucherLine.amount,
        func.row_number()
        .over(partition_by=A.VoucherLine.voucher_id, order_by=A.VoucherLine.line_no)
        .label("n"),
    ).where(A.VoucherLine.entity_id.in_(companies), A.VoucherLine.is_effective.is_(True))
    return in_period(numbered, period).subquery()


def _instruments(companies: list[int], period: Period):  # noqa: ANN202
    """Each voucher's bank instrument and UTR (from its lines that have one)."""
    query = (
        select(
            A.VoucherLine.voucher_id,
            func.max(A.VoucherLine.instrument_number).label("instrument_number"),
            func.max(A.VoucherLine.utr).label("utr"),
        )
        .where(
            A.VoucherLine.entity_id.in_(companies),
            A.VoucherLine.is_effective.is_(True),
            A.VoucherLine.instrument_number.is_not(None) | A.VoucherLine.utr.is_not(None),
        )
        .group_by(A.VoucherLine.voucher_id)
    )
    return in_period(query, period).subquery()


def _side_values(companies: list[int], period: Period, side: Side):  # noqa: ANN202
    """Each voucher's entries on the side's ledgers (canonical sign)."""
    query = (
        select(A.VoucherLine.voucher_id, func.sum(A.VoucherLine.amount).label("value"))
        .where(
            A.VoucherLine.entity_id.in_(companies),
            A.VoucherLine.is_effective.is_(True),
            A.VoucherLine.ledger_id.in_(ledgers_under(companies, side.roles)),
        )
        .group_by(A.VoucherLine.voucher_id)
    )
    return in_period(query, period).subquery()
