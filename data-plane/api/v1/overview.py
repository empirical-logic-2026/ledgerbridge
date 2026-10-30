"""`GET /api/v1/overview`: the Overview app's figures (D1; RPT-001, RPT-006, RPT-008).

For the selected companies (default: all the caller may see, added together: combined,
without inter-company eliminations), a financial year (`financial_year`, the calendar year
it starts in) and an "as at" date inside it (`as_of`, default the year's last day or today,
whichever is earlier). The figures and how they are found: core/overview.py.
"""

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from api.access import CurrentAccess
from api.v1.common import ReportSession
from core.models import accounting as A  # noqa: N812
from core.overview import overview as figures

router = APIRouter(tags=["overview"])


class MonthlySales(BaseModel):
    month: date  # its first day
    net_sales: Decimal


class Overview(BaseModel):
    companies: list[int]
    combined: bool  # several companies added together, without inter-company eliminations
    period_start: date
    as_of: date
    sales: Decimal
    purchases: Decimal
    gross_profit: Decimal | None  # None: no stored statement for the date (see `periods`)
    net_profit: Decimal | None
    cash_and_bank: Decimal
    receivables: Decimal
    payables: Decimal
    monthly_sales: list[MonthlySales]


@router.get("/overview")
def overview(
    session: ReportSession,
    access: CurrentAccess,
    financial_year: int = Query(ge=1900, le=2999),
    company: list[int] | None = Query(default=None),  # noqa: B008
    as_of: date | None = None,
) -> Overview:
    companies = access.entities(company)
    start_month = (
        session.scalar(select(func.min(A.Entity.fy_start_month)).where(A.Entity.id.in_(companies)))
        or 4
    )
    year_start = date(financial_year, start_month, 1)
    year_end = date(financial_year + 1, start_month, 1) - timedelta(days=1)
    on = as_of or min(year_end, date.today())
    if not year_start <= on <= year_end:
        raise HTTPException(status_code=422, detail="'as_of' must fall inside the financial year.")
    found = figures(session, companies, year_start, on)
    return Overview(
        companies=companies,
        combined=len(companies) > 1,
        period_start=found.period_start,
        as_of=found.as_of,
        sales=found.sales,
        purchases=found.purchases,
        gross_profit=found.gross_profit,
        net_profit=found.net_profit,
        cash_and_bank=found.cash_and_bank,
        receivables=found.receivables,
        payables=found.payables,
        monthly_sales=[MonthlySales(month=m, net_sales=n) for m, n in found.monthly_sales],
    )
