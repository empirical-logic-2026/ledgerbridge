"""`GET /api/v1/cost-centres` and `.../{centre_id}`: the Cost Centres page and one cost centre's
allocations (RPT-014). For any combination of the companies the caller may see (`company`,
repeatable; default all, combined) and a period (`month`, repeatable, or `date_from` and
`date_to`). A cost centre is known by its name and category across those companies; one
outside them is 404, like a company outside access. How: core/cost_centres.py.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.access import CurrentAccess
from api.v1.common import ReportSession, formula, parse_period
from api.v1.home import PeriodOut
from core.cost_centres import CentreRow, centre_page, cost_centres, find_centre

router = APIRouter(prefix="/cost-centres", tags=["cost-centres"])


class CentreMonth(BaseModel):
    month: date
    amount: Decimal = formula("F-CC-001")


class CentreOut(BaseModel):
    centre_id: int
    name: str
    category: str | None
    parent: str | None  # the cost centre it sits under (Tally: "Primary" at the top)
    companies: list[int]
    months: list[CentreMonth]  # every month of the period
    total: Decimal = formula("F-CC-001")
    allocations: int = formula("F-CC-003")


class CentresOut(BaseModel):
    companies: list[int]
    combined: bool
    period: PeriodOut
    centres: list[CentreOut]


class AllocationOut(BaseModel):
    company: int
    date: date
    voucher_id: int
    voucher_number: str
    voucher_type: str
    ledger: str
    category: str | None
    amount: Decimal = formula("F-CC-002")


class CentrePageOut(BaseModel):
    centre: CentreOut
    period: PeriodOut
    allocations: list[AllocationOut]
    truncated: bool  # more allocations than shown


def _centre(row: CentreRow, months: list[date]) -> CentreOut:
    return CentreOut(
        centre_id=row.centre_id,
        name=row.name,
        category=row.category,
        parent=row.parent,
        companies=row.companies,
        months=[CentreMonth(month=m, amount=row.months.get(m, Decimal(0))) for m in months],
        total=row.total,
        allocations=row.allocations,
    )


@router.get("")
def centres(
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
) -> CentresOut:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    months = period.month_starts()
    return CentresOut(
        companies=companies,
        combined=len(companies) > 1,
        period=PeriodOut(start=period.start, end=period.end, months=list(period.months)),
        centres=[_centre(row, months) for row in cost_centres(session, companies, period)],
    )


@router.get("/{centre_id}")
def centre(
    centre_id: int,
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
) -> CentrePageOut:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    ref = find_centre(session, companies, centre_id)
    if ref is None:
        raise HTTPException(404, "No such cost centre in the selected companies.")
    page = centre_page(session, companies, ref, period)
    return CentrePageOut(
        centre=_centre(page.centre, period.month_starts()),
        period=PeriodOut(start=period.start, end=period.end, months=list(period.months)),
        allocations=[
            AllocationOut(
                company=a.company, date=a.on, voucher_id=a.voucher_id,
                voucher_number=a.voucher_number, voucher_type=a.voucher_type, ledger=a.ledger,
                category=a.category, amount=a.amount,
            )
            for a in page.allocations
        ],
        truncated=page.truncated,
    )  # fmt: skip
