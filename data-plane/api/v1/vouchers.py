"""`GET /api/v1/vouchers/{voucher_id}`: one voucher for the dashboard's voucher page (Books ›
Voucher; RPT-007): its header, ledger lines, bill allocations and stock lines. A voucher
outside the companies the caller may see (or deleted) is 404, like a company outside access.
Read only; no UTR. How: core/vouchers.py.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.access import CurrentAccess
from api.v1.common import ReportSession, formula
from core.vouchers import voucher_page

router = APIRouter(prefix="/vouchers", tags=["vouchers"])


class VoucherLineOut(BaseModel):
    line_no: int
    ledger_id: int
    ledger: str
    debit: Decimal | None = formula("F-TRN-001")
    credit: Decimal | None = formula("F-TRN-001")
    effective: bool  # posts to the books (cancelled and optional vouchers don't)
    instrument_number: str | None  # a cheque number


class VoucherBillOut(BaseModel):
    ledger: str
    bill_type: str
    bill_name: str | None
    bill_date: date | None
    due_date: date | None
    debit: Decimal | None = formula("F-TRN-001")
    credit: Decimal | None = formula("F-TRN-001")


class VoucherStockOut(BaseModel):
    line_no: int
    item_id: int
    item: str
    godown: str | None
    other_godown: str | None
    batch: str | None
    quantity: Decimal = formula("F-STK-014")
    rate: Decimal | None = formula("F-STK-015")
    amount: Decimal = formula("F-STK-008")


class VoucherOut(BaseModel):
    voucher_id: int
    company: int
    date: date
    voucher_type: str
    number: str
    party_id: int | None
    party: str | None
    reference: str | None
    narration: str | None
    cancelled: bool
    optional: bool
    total_debit: Decimal = formula("F-VCH-001")
    total_credit: Decimal = formula("F-VCH-001")
    lines: list[VoucherLineOut]
    bills: list[VoucherBillOut]
    stock: list[VoucherStockOut]


def _sides(amount: Decimal) -> tuple[Decimal | None, Decimal | None]:
    """(debit, credit): the amount on its side, shown positive."""
    return (amount, None) if amount >= 0 else (None, -amount)


@router.get("/{voucher_id}")
def voucher(voucher_id: int, session: ReportSession, access: CurrentAccess) -> VoucherOut:
    page = voucher_page(session, access.entities(None), voucher_id)
    if page is None:
        raise HTTPException(404, "No such voucher in the companies you can see.")
    return VoucherOut(
        voucher_id=page.voucher_id, company=page.company, date=page.date,
        voucher_type=page.voucher_type, number=page.number, party_id=page.party_id,
        party=page.party, reference=page.reference, narration=page.narration,
        cancelled=page.cancelled, optional=page.optional, total_debit=page.debit,
        total_credit=page.credit,
        lines=[
            VoucherLineOut(
                line_no=x.line_no, ledger_id=x.ledger_id, ledger=x.ledger,
                debit=_sides(x.amount)[0], credit=_sides(x.amount)[1], effective=x.effective,
                instrument_number=x.instrument_number,
            )
            for x in page.lines
        ],
        bills=[
            VoucherBillOut(
                ledger=b.ledger, bill_type=b.bill_type, bill_name=b.bill_name,
                bill_date=b.bill_date, due_date=b.due_date, debit=_sides(b.amount)[0],
                credit=_sides(b.amount)[1],
            )
            for b in page.bills
        ],
        stock=[
            VoucherStockOut(
                line_no=s.line_no, item_id=s.item_id, item=s.item, godown=s.godown,
                other_godown=s.other_godown, batch=s.batch, quantity=s.quantity, rate=s.rate,
                amount=s.amount,
            )
            for s in page.stock
        ],
    )  # fmt: skip
