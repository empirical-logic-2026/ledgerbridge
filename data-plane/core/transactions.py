"""The Transactions page (RPT-014; formula F-TRN-001): one row per ledger line of the
selected companies and period, with its voucher's date, type, number, reference, party and
narration, the line's ledger and amount, the voucher's other ledgers (particulars), and the
line's bills, cost centres and bank instrument. Source-independent: read from the books.

- **Lines:** effective lines (`is_effective`: not cancelled or optional, of a type that posts
  to the books) of vouchers that aren't deleted, the earliest first; at most `LIMIT`, with
  `truncated` saying when there were more.
- **Particulars:** the voucher's ledgers on the other side of the line (credit lines for a
  debit line and the reverse), as the source's ledger report shows them; every other ledger
  when none is on the other side. Each ledger once, in the voucher's order.
- **Amounts:** canonical sign, debit positive: a debit line's amount is its Debit, a credit
  line's its Credit (shown positive).
- **Order number:** the orders the voucher is made against (`voucher_orders`), else the
  orders its stock lines are against (`inventory_lines.order_number`); each once.
- **GST:** the voucher's registration (tax unit), place of supply, e-invoice and e-way bill,
  the party's registration type, and the line's own GST rates per duty head, when it has any
  (otherwise the rate is the item's or ledger's: not shown here).
- **No UTR:** the line's UTR and where it was found stay in the database
  (`voucher_lines.utr`, `utr_source`) but are never read here, so no page or export
  shows them.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from core.home import in_period
from core.models import accounting as A  # noqa: N812
from core.report_periods import Period

LIMIT = 20_000  # rows on the page
JOIN = ", "


@dataclass
class TransactionRow:
    line_id: int
    company: int
    on: date
    voucher_id: int
    voucher_type: str
    voucher_number: str
    reference: str | None
    party_id: int | None
    party: str | None
    gstin: str | None
    ledger_id: int
    ledger: str
    particulars: str | None
    debit: Decimal | None
    credit: Decimal | None
    narration: str | None
    bills: str | None
    cost_centres: str | None
    order_number: str | None  # the sales or purchase orders the voucher is made against
    cheque: str | None  # a bank line's cheque or instrument number
    transaction_type: str | None
    instrument_date: date | None
    bank_cleared_date: date | None
    tally_bank_entry_id: str | None  # the source's own id for the bank entry, never a UTR
    gst_registration: str | None = None  # the company's tax unit the voucher is under
    place_of_supply: str | None = None
    party_gst_registration_type: str | None = None
    gst_rates: str | None = None  # the line's own, e.g. "CGST 9%, SGST/UTGST 9%"
    irn: str | None = None
    irn_date: date | None = None
    eway_bill_number: str | None = None
    eway_bill_date: date | None = None


@dataclass
class TransactionPage:
    rows: list[TransactionRow]
    truncated: bool


def _joined(values: list[str]) -> str | None:
    """Each value once, in order; None when there are none."""
    unique = list(dict.fromkeys(v for v in values if v))
    return JOIN.join(unique) if unique else None


def _lines(session: Session, companies: list[int], period: Period):  # noqa: ANN202
    party = aliased(A.Party)
    query = in_period(
        select(
            A.VoucherLine.id, A.VoucherLine.entity_id, A.VoucherLine.voucher_date,
            A.Voucher.id, A.VoucherType.name, A.Voucher.voucher_number,
            A.Voucher.reference_number, A.Voucher.party_id, party.name, party.gstin,
            A.VoucherLine.ledger_id, A.Ledger.name, A.VoucherLine.amount, A.Voucher.narration,
            A.VoucherLine.instrument_number, A.VoucherLine.transaction_type,
            A.VoucherLine.instrument_date,
            A.VoucherLine.bank_cleared_date, A.VoucherLine.tally_bank_entry_id,
            A.Voucher.gst_registration, A.Voucher.place_of_supply,
            party.gst_registration_type, A.Voucher.irn, A.Voucher.irn_date,
            A.Voucher.eway_bill_number, A.Voucher.eway_bill_date,
        )
        .join(A.Voucher, A.Voucher.id == A.VoucherLine.voucher_id)
        .join(A.VoucherType, A.VoucherType.id == A.Voucher.voucher_type_id)
        .join(A.Ledger, A.Ledger.id == A.VoucherLine.ledger_id)
        .outerjoin(party, party.id == A.Voucher.party_id)
        .where(
            A.VoucherLine.entity_id.in_(companies),
            A.VoucherLine.is_effective.is_(True),
            A.Voucher.is_deleted.is_(False),
        ),
        period,
    ).order_by(A.VoucherLine.voucher_date, A.Voucher.id, A.VoucherLine.line_no)  # fmt: skip
    return session.execute(query.limit(LIMIT + 1)).all()


def _voucher_ledgers(
    session: Session, voucher_ids: set[int]
) -> dict[int, list[tuple[int, str, Decimal]]]:
    """Each voucher's effective lines: (line id, ledger, amount), in the voucher's order."""
    found: dict[int, list[tuple[int, str, Decimal]]] = defaultdict(list)
    for chunk in _chunks(sorted(voucher_ids)):
        for vid, line_id, ledger, amount in session.execute(
            select(A.VoucherLine.voucher_id, A.VoucherLine.id, A.Ledger.name, A.VoucherLine.amount)
            .join(A.Ledger, A.Ledger.id == A.VoucherLine.ledger_id)
            .where(A.VoucherLine.voucher_id.in_(chunk), A.VoucherLine.is_effective.is_(True))
            .order_by(A.VoucherLine.voucher_id, A.VoucherLine.line_no)
        ):
            found[int(vid)].append((int(line_id), ledger, Decimal(amount)))
    return found


def _particulars(
    line_id: int, amount: Decimal, lines: list[tuple[int, str, Decimal]]
) -> str | None:
    others = [(ledger, other) for lid, ledger, other in lines if lid != line_id]
    opposite = [ledger for ledger, other in others if (other < 0) != (amount < 0) and other != 0]
    return _joined(opposite or [ledger for ledger, _ in others])


def _per_line(session: Session, line_ids: list[int], query) -> dict[int, list[str]]:  # noqa: ANN001
    """Names per line from a query of (line id, name) limited by `line_ids`."""
    found: dict[int, list[str]] = defaultdict(list)
    for chunk in _chunks(line_ids):
        for line_id, name in session.execute(query(chunk)):
            if name:
                found[int(line_id)].append(name)
    return found


def _bills(chunk: list[int]):  # noqa: ANN202
    return (
        select(A.BillAllocation.voucher_line_id, A.BillAllocation.bill_name)
        .where(A.BillAllocation.voucher_line_id.in_(chunk))
        .order_by(A.BillAllocation.voucher_line_id, A.BillAllocation.id)
    )


def _line_gst_rates(session: Session, line_ids: list[int]) -> dict[int, list[str]]:
    """Each line's own GST rates as "<head> <rate>%" (e.g. "CGST 9%"), in the source's order."""
    found: dict[int, list[str]] = defaultdict(list)
    for chunk in _chunks(line_ids):
        for line_id, head, rate in session.execute(
            select(A.LineGstRate.voucher_line_id, A.LineGstRate.duty_head, A.LineGstRate.rate)
            .where(A.LineGstRate.voucher_line_id.in_(chunk))
            .order_by(A.LineGstRate.voucher_line_id, A.LineGstRate.id)
        ):
            found[int(line_id)].append(f"{head} {Decimal(rate).normalize():f}%")
    return found


def _cost_centres(chunk: list[int]):  # noqa: ANN202
    return (
        select(A.LineCostAllocation.voucher_line_id, A.CostCentre.name)
        .join(A.CostCentre, A.CostCentre.id == A.LineCostAllocation.cost_centre_id)
        .where(A.LineCostAllocation.voucher_line_id.in_(chunk))
        .order_by(A.LineCostAllocation.voucher_line_id, A.LineCostAllocation.id)
    )


def _orders(session: Session, voucher_ids: list[int]) -> dict[int, str]:
    """Each voucher's order numbers: the orders it names (its order list), else the orders
    its stock lines are against."""
    named: dict[int, list[str]] = defaultdict(list)
    on_lines: dict[int, list[str]] = defaultdict(list)
    for chunk in _chunks(voucher_ids):
        for vid, number in session.execute(
            select(A.VoucherOrder.voucher_id, A.VoucherOrder.order_number)
            .where(A.VoucherOrder.voucher_id.in_(chunk))
            .order_by(A.VoucherOrder.voucher_id, A.VoucherOrder.id)
        ):
            named[int(vid)].append(number)
        for vid, number in session.execute(
            select(A.InventoryLine.voucher_id, A.InventoryLine.order_number)
            .where(A.InventoryLine.voucher_id.in_(chunk), A.InventoryLine.order_number.is_not(None))
            .order_by(A.InventoryLine.voucher_id, A.InventoryLine.line_no)
        ):
            on_lines[int(vid)].append(number)
    found = {}
    for vid in voucher_ids:
        joined = _joined(named.get(vid) or on_lines.get(vid) or [])
        if joined:
            found[vid] = joined
    return found


def _chunks(ids: list[int], size: int = 1_000) -> list[list[int]]:
    return [ids[i : i + size] for i in range(0, len(ids), size)]


def transactions(session: Session, companies: list[int], period: Period) -> TransactionPage:
    """Every effective ledger line of the companies in the period, the earliest first."""
    found = _lines(session, companies, period)
    truncated = len(found) > LIMIT
    found = found[:LIMIT]
    voucher_lines = _voucher_ledgers(session, {int(r[3]) for r in found})
    line_ids = [int(r[0]) for r in found]
    bills = _per_line(session, line_ids, _bills)
    centres = _per_line(session, line_ids, _cost_centres)
    orders = _orders(session, sorted({int(r[3]) for r in found}))
    rates = _line_gst_rates(session, line_ids)
    rows = []
    for (line_id, entity, on, vid, vtype, number, reference, party_id, party, gstin, ledger_id,
         ledger, amount, narration, cheque, transaction_type, instrument_date,
         cleared, tally_id, registration, supply, party_type, irn, irn_date, eway,
         eway_date) in found:  # fmt: skip
        amount = Decimal(amount)
        rows.append(
            TransactionRow(
                line_id=int(line_id), company=int(entity), on=on, voucher_id=int(vid),
                voucher_type=vtype, voucher_number=number, reference=reference,
                party_id=int(party_id) if party_id is not None else None, party=party,
                gstin=gstin, ledger_id=int(ledger_id), ledger=ledger,
                particulars=_particulars(int(line_id), amount, voucher_lines[int(vid)]),
                debit=amount if amount > 0 else None,
                credit=-amount if amount < 0 else None,
                narration=narration, bills=_joined(bills[int(line_id)]),
                cost_centres=_joined(centres[int(line_id)]),
                order_number=orders.get(int(vid)),
                cheque=cheque,
                transaction_type=transaction_type, instrument_date=instrument_date,
                bank_cleared_date=cleared, tally_bank_entry_id=tally_id,
                gst_registration=registration, place_of_supply=supply,
                party_gst_registration_type=party_type, gst_rates=_joined(rates[int(line_id)]),
                irn=irn, irn_date=irn_date, eway_bill_number=eway, eway_bill_date=eway_date,
            )
        )  # fmt: skip
    return TransactionPage(rows, truncated)
