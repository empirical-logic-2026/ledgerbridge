"""`GET /api/v1/monthly/{side}`: monthly sales (`sales`) and monthly purchases (`purchases`)
(D2; docs/design/dashboard.md Section 0.2): each month's gross, returns, other adjustments,
net and invoices, and the closing balance (the net from the start of the financial year to
the month's end, as the source's monthly summary of the Sales or Purchase Accounts group
shows it).

For any combination of the companies the caller may see (`company`, repeatable; default all,
combined), a period (`month`, repeatable, or `date_from` and `date_to`) and the facets by name
(`party`, `voucher_type`, repeatable). The figures: core/sales.py.
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.access import CurrentAccess
from api.v1.common import ReportSession, parse_period
from api.v1.home import PeriodOut
from api.v1.registers import SIDES
from api.v1.sales import facet_names
from core.sales import Facets, monthly_with_closing

router = APIRouter(prefix="/monthly", tags=["monthly"])


class MonthOut(BaseModel):
    month: date
    gross: Decimal
    returns: Decimal  # negative
    other: Decimal
    net: Decimal
    invoices: int
    closing: Decimal  # the net from the start of the financial year to the month's end


class MonthlyOut(BaseModel):
    side: str
    companies: list[int]
    combined: bool
    period: PeriodOut
    months: list[MonthOut]


@router.get("/{side}")
def monthly(
    side: Literal["sales", "purchases"],
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
    party: list[str] | None = Query(default=None),  # noqa: B008
    voucher_type: list[str] | None = Query(default=None),  # noqa: B008
) -> MonthlyOut:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    facets = Facets(facet_names(party, "party"), facet_names(voucher_type, "voucher type"))
    found = monthly_with_closing(session, companies, period, facets, SIDES[side])
    return MonthlyOut(
        side=side,
        companies=companies,
        combined=len(companies) > 1,
        period=PeriodOut(start=period.start, end=period.end, months=list(period.months)),
        months=[
            MonthOut(
                month=m,
                gross=t.gross,
                returns=t.returns,
                other=t.other,
                net=t.net,
                invoices=t.invoices,
                closing=closing,
            )
            for m, t, closing in found
        ],
    )
