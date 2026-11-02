"""`GET /api/v1/sales/dashboard`: the Sales dashboard (D2; docs/design/dashboard.md Section
0.2, screen 7).

For any combination of the companies the caller may see (`company`, repeatable; default all,
combined, without inter-company eliminations), a period (`month`, repeatable, or `date_from`
and `date_to`) and the top filter bar's facets by name (`customer`, `channel`: voucher types,
repeatable). `compare` adds the previous period or last year (api/v1/common.py) to the key
figures. The
figures and how they are found: core/sales.py.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.access import CurrentAccess
from api.v1.common import (
    Comparable,
    ComparedWith,
    CompareParam,
    ReportSession,
    SpanParam,
    compared_with,
    formula,
    parse_period,
)
from api.v1.home import PeriodOut, change_pct
from core.sales import Facets, Totals, by_channel, dashboard

router = APIRouter(prefix="/sales", tags=["sales"])

MAX_FACET_VALUES = 50
MAX_NAME = 255


class KeyFigure(Comparable):
    value: Decimal | None
    before: Decimal | None = None  # the comparison period's
    change_pct: Decimal | None = formula(
        "F-CMP-001", default=None
    )  # against `before`, one decimal; None without one


class KeyFigures(BaseModel):
    net_sales: KeyFigure = formula("F-SAL-004")
    invoices: KeyFigure = formula("F-SAL-005")
    average_invoice: KeyFigure = formula("F-SAL-006")
    sales_returns: KeyFigure = formula("F-SAL-007")  # returns as a positive amount: lower is better


class MonthSales(BaseModel):
    month: date
    gross: Decimal = formula("F-SAL-001")
    returns: Decimal = formula("F-SAL-002")  # negative
    other: Decimal = formula("F-SAL-003")
    net: Decimal = formula("F-SAL-004")
    invoices: int = formula("F-SAL-005")


class PartySales(BaseModel):
    company: int
    party_id: int
    name: str
    net_sales: Decimal = formula("F-SAL-012")
    invoices: int = formula("F-SAL-005")


class InvoiceOut(BaseModel):
    voucher_id: int
    company: int
    date: date
    number: str
    voucher_type: str
    party_id: int | None
    party: str | None
    amount: Decimal = formula("F-SAL-014")


class SalesDashboard(BaseModel):
    companies: list[int]
    combined: bool  # several companies added together, without inter-company eliminations
    period: PeriodOut
    compared_with: ComparedWith | None
    key_figures: KeyFigures
    monthly: list[MonthSales]
    top_customers: list[PartySales]
    other_customers: Decimal = formula("F-SAL-013")  # the rest, and sales without a party
    customers: int = formula("F-SAL-011")  # how many customers had sales
    largest_invoices: list[InvoiceOut]


def facet_names(values: list[str] | None, name: str) -> tuple[str, ...]:
    """Facet values as given (names), bounded in number and length."""
    values = values or []
    if len(values) > MAX_FACET_VALUES or any(len(v) > MAX_NAME for v in values):
        raise HTTPException(
            422, f"At most {MAX_FACET_VALUES} {name} names of {MAX_NAME} characters."
        )
    return tuple(dict.fromkeys(values))


@router.get("/dashboard")
def sales_dashboard(
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
    compare: CompareParam | None = None,
    span: SpanParam | None = None,
    customer: list[str] | None = Query(default=None),  # noqa: B008
    channel: list[str] | None = Query(default=None),  # noqa: B008
) -> SalesDashboard:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    facets = Facets(facet_names(customer, "customer"), facet_names(channel, "channel"))
    before, described = compared_with(period, compare, span)
    found = dashboard(session, companies, period, before, facets)
    return SalesDashboard(
        companies=companies,
        combined=len(companies) > 1,
        period=PeriodOut(start=period.start, end=period.end, months=list(period.months)),
        compared_with=described,
        key_figures=_key_figures(found.totals, found.before),
        monthly=[
            MonthSales(
                month=m,
                gross=t.gross,
                returns=t.returns,
                other=t.other,
                net=t.net,
                invoices=t.invoices,
            )
            for m, t in found.monthly
        ],  # fmt: skip
        top_customers=[
            PartySales(
                company=p.company,
                party_id=p.party_id,
                name=p.name or "",
                net_sales=p.net,
                invoices=p.invoices,
            )
            for p in found.top_parties
            if p.party_id is not None
        ],  # fmt: skip
        other_customers=found.other_parties,
        customers=found.parties,
        largest_invoices=[
            InvoiceOut(
                voucher_id=i.voucher_id,
                company=i.company,
                date=i.on,
                number=i.number,
                voucher_type=i.voucher_type,
                party_id=i.party_id,
                party=i.party,
                amount=i.amount,
            )
            for i in found.largest
        ],  # fmt: skip
    )


def _key_figures(now: Totals, before: Totals | None) -> KeyFigures:
    def figure(value: Decimal | int | None, last: Decimal | int | None) -> KeyFigure:
        now_value = None if value is None else Decimal(value)
        last_value = None if last is None else Decimal(last)
        return KeyFigure(
            value=now_value, before=last_value, change_pct=change_pct(now_value, last_value)
        )

    def returns(t: Totals) -> Decimal:
        return -t.returns

    return KeyFigures(
        net_sales=figure(now.net, before.net if before else None),
        invoices=figure(now.invoices, before.invoices if before else None),
        average_invoice=figure(now.average_invoice, before.average_invoice if before else None),
        sales_returns=figure(returns(now), returns(before) if before else None),
    )


class ChannelMonth(BaseModel):
    month: date
    net: Decimal = formula("F-SAL-009")


class ChannelOut(BaseModel):
    name: str  # a voucher type's name
    months: list[ChannelMonth]  # every month of the period, 0 where none
    gross: Decimal = formula("F-SAL-001")
    returns: Decimal = formula("F-SAL-002")
    other: Decimal = formula("F-SAL-003")
    net: Decimal = formula("F-SAL-009")
    invoices: int = formula("F-SAL-005")
    share_pct: Decimal | None = formula("F-SAL-010")  # of the selection's net sales, one decimal


class ChannelsOut(BaseModel):
    companies: list[int]
    combined: bool
    period: PeriodOut
    channels: list[ChannelOut]  # the largest net sales first


@router.get("/channels")
def sales_by_channel(
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
    customer: list[str] | None = Query(default=None),  # noqa: B008
    channel: list[str] | None = Query(default=None),  # noqa: B008
) -> ChannelsOut:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    facets = Facets(facet_names(customer, "customer"), facet_names(channel, "channel"))
    found = by_channel(session, companies, period, facets)
    total = sum((c.totals.net for c in found), Decimal(0))
    return ChannelsOut(
        companies=companies,
        combined=len(companies) > 1,
        period=PeriodOut(start=period.start, end=period.end, months=list(period.months)),
        channels=[
            ChannelOut(
                name=c.name,
                months=[
                    ChannelMonth(month=m, net=c.months.get(m, Decimal(0)))
                    for m in period.month_starts()
                ],
                gross=c.totals.gross,
                returns=c.totals.returns,
                other=c.totals.other,
                net=c.totals.net,
                invoices=c.totals.invoices,
                share_pct=(c.totals.net / total * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)
                if total
                else None,
            )
            for c in found
        ],
    )
