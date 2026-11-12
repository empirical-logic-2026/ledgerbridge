"""`GET /api/v1/ageing/{customers|vendors}`: receivables and payables with ageing (RPT-004,
RPT-014; docs/design/dashboard.md Section 0.4), as at the period's end.

For any combination of the companies the caller may see (`company`, repeatable; default all,
combined) and a period (`month`, repeatable, or `date_from` and `date_to`): each party, known by
name across those companies, with its balance due, its outstanding bills in six buckets (by
days past the due date, or with `basis=bill_date` since the bill's date), what isn't in bills
in four parts, every open bill with the voucher that raised it, and the average days to pay
of the bills settled in the period. How: core/ageing.py.
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.access import CurrentAccess
from api.v1.common import ReportSession, formula, parse_period
from core.ageing import AgeingRow, OpenBill, ageing, bucket
from core.parties import PaymentStatus, party_payment_status

router = APIRouter(prefix="/ageing", tags=["ageing"])


class Buckets(BaseModel):
    """Outstanding bills by days past the due date, or since the bill's date (F-PTY-014)."""

    not_due: Decimal = formula("F-PTY-014")
    days_1_30: Decimal = formula("F-PTY-014")
    days_31_60: Decimal = formula("F-PTY-014")
    days_61_90: Decimal = formula("F-PTY-014")
    days_91_180: Decimal = formula("F-PTY-014")
    over_180: Decimal = formula("F-PTY-014")


class NotInBills(BaseModel):
    """The balance not in bills (F-PTY-013), in four parts."""

    total: Decimal = formula("F-PTY-013")
    on_account: Decimal = formula("F-PTY-015")
    opening_difference: Decimal = formula("F-PTY-016")
    revaluation: Decimal = formula("F-PTY-020")
    other: Decimal = formula("F-PTY-017")


class AgeingRowOut(BaseModel):
    party_id: int
    name: str
    balance: Decimal = formula("F-PTY-001")
    buckets: Buckets
    overdue: Decimal = formula("F-PTY-002")
    over_90: Decimal = formula("F-PTY-018")
    uncovered: Decimal = formula("F-PTY-013")  # the balance the stored bills don't cover
    not_in_bills: NotInBills
    status: Literal["overdue", "current"]
    payment_status: PaymentStatus


class OpenBillOut(BaseModel):
    party_id: int
    party: str
    bill: str
    bill_date: date
    due_date: date
    days: int = formula("F-PTY-014")  # by the basis
    overdue_days: int = formula("F-PTY-005")
    bucket: str
    amount: Decimal = formula("F-PTY-004")
    voucher_id: int | None  # the voucher that raised it; None for an opening bill


class AgeingOut(BaseModel):
    kind: str
    companies: list[int]
    combined: bool
    as_of: date
    basis: Literal["due_date", "bill_date"]
    rows: list[AgeingRowOut]
    total: AgeingRowOut  # every row added up (party_id 0)
    bills: list[OpenBillOut]
    days_to_pay: Decimal | None = formula("F-PTY-019")  # bills settled in the period


def _row(r: AgeingRow) -> AgeingRowOut:
    payment_status = party_payment_status(r.balance, r.overdue, r.pending, r.advance)
    return AgeingRowOut(
        party_id=r.party_id,
        name=r.name,
        balance=r.balance,
        buckets=Buckets(**r.buckets),
        overdue=r.overdue,
        over_90=r.over_90,
        uncovered=r.uncovered,
        not_in_bills=NotInBills(
            total=r.uncovered,
            on_account=r.on_account,
            opening_difference=r.opening_difference,
            revaluation=r.revaluation,
            other=r.other,
        ),  # fmt: skip
        status="overdue" if payment_status == "overdue" else "current",
        payment_status=payment_status,
    )


def _bill(b: OpenBill) -> OpenBillOut:
    return OpenBillOut(
        party_id=b.party_id, party=b.party, bill=b.name, bill_date=b.bill_date, due_date=b.due,
        days=b.days, overdue_days=b.overdue_days, bucket=bucket(b.days), amount=b.amount,
        voucher_id=b.voucher_id,
    )  # fmt: skip


@router.get("/{kind}")
def ageing_of(
    kind: Literal["customers", "vendors"],
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
    basis: Literal["due_date", "bill_date"] = "due_date",
) -> AgeingOut:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    found = ageing(session, companies, period.end, kind, basis, since=period.start)
    return AgeingOut(
        kind=kind,
        companies=companies,
        combined=len(companies) > 1,
        as_of=period.end,
        basis=basis,
        rows=[_row(r) for r in found.rows],
        total=_row(found.total()),
        bills=[_bill(b) for b in found.bills],
        days_to_pay=found.days_to_pay,
    )
