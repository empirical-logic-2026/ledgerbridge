"""`GET /api/v1/cash-flow`: the Cash Flow module's cash movement (RPT-014; docs/design/
dashboard.md Section 0.4): cash and bank at the start and end of the period and the money in
and out by what it was for, with the months' in and out. For any combination of the companies
the caller may see (`company`, repeatable; default all, combined) and a period (`month`,
repeatable, or `date_from` and `date_to`). How: core/cash_flow.py.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.access import CurrentAccess
from api.v1.common import ReportSession, formula, parse_period
from core.cash_flow import cash_flow

router = APIRouter(tags=["cash-flow"])


class MovementOut(BaseModel):
    key: str  # customers, suppliers, income, expenses, taxes, loans, capital, assets, ...
    label: str
    inflow: Decimal = formula("F-CF-001")
    outflow: Decimal = formula("F-CF-001")  # positive
    net: Decimal = formula("F-CF-001")


class CashMonthOut(BaseModel):
    month: date
    inflow: Decimal = formula("F-CF-002")
    outflow: Decimal = formula("F-CF-002")


class CashFlowOut(BaseModel):
    companies: list[int]
    combined: bool
    start: date
    end: date
    opening: Decimal = formula("F-BAL-002")  # the day before the start
    closing: Decimal = formula("F-BAL-002")
    movements: list[MovementOut]
    monthly: list[CashMonthOut]


@router.get("/cash-flow")
def cash_movement(
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
) -> CashFlowOut:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    found = cash_flow(session, companies, period)
    return CashFlowOut(
        companies=companies,
        combined=len(companies) > 1,
        start=period.start,
        end=period.end,
        opening=found.opening,
        closing=found.closing,
        movements=[
            MovementOut(key=m.key, label=m.label, inflow=m.inflow, outflow=m.outflow, net=m.net)
            for m in found.movements
        ],
        monthly=[CashMonthOut(month=m, inflow=i, outflow=o) for m, i, o in found.monthly],
    )
