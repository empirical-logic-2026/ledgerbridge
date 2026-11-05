"""`GET /api/v1/home`: the dashboard home's figures (D1; docs/design/dashboard.md Section 0.1).

For any combination of the companies the caller may see (`company`, repeatable; default all,
added together: combined, without inter-company eliminations) and a period: whole months
(`month=2026-04`, repeatable, adjacent or not) or a date range (`date_from`, `date_to`).
`compare` adds the previous period or last year (api/v1/common.py) to the figures, as
their `before` values. The figures and
how they are found: core/home.py; periods and statement windows: core/report_periods.py;
every formula: docs/formulas.md. The key figures: revenue (net sales), gross margin, net
profit, both as a percentage of revenue, and the customer count (core/sales.py).
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from fastapi import APIRouter, Query
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
from core.home import BS_FIGURES, PL_FIGURES, StatementFigures, home
from core.overview import TopCustomer, TrendMonth, top_customers, trend
from core.parties import PaymentStatus, party_payment_status
from core.sales import party_count

router = APIRouter(tags=["home"])

TOP_CHANNELS = 4  # the largest voucher types; the rest are "Others"
OTHERS = "Others"


class Figure(Comparable):
    value: Decimal | None
    before: Decimal | None = None  # the comparison period's
    change_pct: Decimal | None = formula(
        "F-CMP-001", default=None
    )  # against `before`, one decimal; None without one


class Ratio(Comparable):
    """A percentage of revenue, one decimal; the change in percentage points."""

    value: Decimal | None
    before: Decimal | None = None
    change_pts: Decimal | None = formula("F-CMP-003", default=None)


class Count(Comparable):
    value: int
    before: int | None = None
    change_pct: Decimal | None = formula("F-CMP-001", default=None)


class ProfitLoss(BaseModel):
    available: bool
    reason: str | None  # why the figures aren't available
    as_of: date | None  # the last statement date used
    shifted: bool  # a month ran to a later stored date (the source's Educational mode)
    cut: bool  # a date range's figures end at `as_of`, the last stored date within it
    before_reason: str | None  # why the comparison period has no figures
    net_sales: Figure = formula("F-PL-001")
    cost_of_sales: Figure = formula("F-PL-002")
    gross_profit: Figure = formula("F-PL-003")
    net_profit: Figure = formula("F-PL-004")
    gross_margin_pct: Ratio = formula("F-PL-005")  # gross profit / net sales
    net_profit_pct: Ratio = formula("F-PL-006")  # net profit / net sales
    other_costs: Figure = formula("F-PL-009")  # gross profit - net profit
    cost_of_sales_pct: Ratio = formula("F-PL-010")  # cost of sales / net sales
    other_costs_pct: Ratio = formula("F-PL-010")  # other costs / net sales


class BalanceSheet(BaseModel):
    available: bool
    reason: str | None
    as_of: date | None
    total_assets: Decimal | None = formula("F-BS-001")
    current_assets: Decimal | None = formula("F-BS-002")
    current_liabilities: Decimal | None = formula("F-BS-003")
    capital_and_reserves: Decimal | None = formula("F-BS-004")


class Balances(BaseModel):
    as_of: date
    cash_and_bank: Decimal = formula("F-BAL-002")
    receivables: Decimal = formula("F-BAL-003")
    payables: Decimal = formula("F-BAL-004")
    stock_value: Decimal | None = formula("F-BAL-005")  # the source's, stored with the statements
    stock_value_as_of: date | None


class MonthFigures(BaseModel):
    month: date
    sales: Decimal = formula("F-SAL-004")
    purchases: Decimal = formula("F-PUR-001")
    gross_profit: Decimal | None = formula(
        "F-PL-003"
    )  # from the stored statements; None without them
    net_profit: Decimal | None = formula("F-PL-004")


class Channel(BaseModel):
    name: str  # a voucher type's name, or "Others"
    net_sales: Decimal = formula("F-SAL-009")


class CompanyShare(BaseModel):
    company: int
    net_sales: Decimal = formula("F-SAL-004")
    share_pct: Decimal | None = formula("F-SAL-015")  # of the selection's net sales, one decimal


class TrendOut(BaseModel):
    """One month of the key cards' twelve-month trend (the sparklines; F-OVR-001)."""

    month: date
    net_sales: Decimal = formula("F-SAL-004")
    gross_profit: Decimal | None = formula("F-PL-003")  # None without the month's statements
    net_profit: Decimal | None = formula("F-PL-004")
    cash_and_bank: Decimal = formula("F-BAL-002")
    customers: int = formula("F-SAL-011")


class SummaryLine(BaseModel):
    """A line of the Overview's Profit & Loss summary, this period against last year."""

    key: str  # net_sales, cost_of_sales, gross_profit, gross_margin_pct, net_profit, ...
    label: str
    unit: Literal["amount", "percent"]
    higher_is_better: bool
    value: Decimal | None = formula("F-OVR-003")
    last_year: Decimal | None = formula("F-OVR-003")
    change_pct: Decimal | None = formula("F-CMP-001")  # amounts
    change_pts: Decimal | None = formula("F-CMP-003")  # percentages


class TopCustomerOut(BaseModel):
    party_id: int
    name: str
    net_sales: Decimal = formula("F-SAL-012")
    share_pct: Decimal | None = formula("F-OVR-004")  # of the period's net sales
    balance: Decimal = formula("F-PTY-001")
    overdue: Decimal = formula("F-PTY-002")
    status: Literal["overdue", "current"]
    payment_status: PaymentStatus


class PeriodOut(BaseModel):
    start: date
    end: date
    months: list[date]  # first days; empty for a date range


class Home(BaseModel):
    companies: list[int]
    combined: bool  # several companies added together, without inter-company eliminations
    period: PeriodOut
    compared_with: ComparedWith | None
    profit_loss: ProfitLoss
    balance_sheet: BalanceSheet
    balances: Balances
    customers: Count = formula("F-SAL-011")  # with sales in the period, by name
    monthly: list[MonthFigures]
    channels: list[Channel]
    by_company: list[CompanyShare]
    trend: list[TrendOut]  # the twelve months up to the period's end (F-OVR-001)
    summary: list[SummaryLine]  # the Profit & Loss against last year
    summary_reason: str | None  # why last year has no figures
    top_customers: list[TopCustomerOut]  # F-OVR-002


@router.get("/home")
def dashboard_home(
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
    compare: CompareParam | None = None,
    span: SpanParam | None = None,
) -> Home:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    before, described = compared_with(period, compare, span)
    found = home(session, companies, period, before)
    customers = party_count(session, companies, period)
    customers_before = party_count(session, companies, before) if before else None
    return Home(
        companies=companies,
        combined=len(companies) > 1,
        period=PeriodOut(start=period.start, end=period.end, months=list(period.months)),
        compared_with=described,
        profit_loss=_profit_loss(found.profit_loss, found.profit_loss_before),
        balance_sheet=_balance_sheet(found.balance_sheet),
        balances=Balances(
            as_of=period.end,
            cash_and_bank=found.cash_and_bank,
            receivables=found.receivables,
            payables=found.payables,
            stock_value=found.stock_value,
            stock_value_as_of=found.profit_loss.as_of if found.stock_value is not None else None,
        ),
        customers=Count(
            value=customers,
            before=customers_before,
            change_pct=change_pct(Decimal(customers), _decimal(customers_before)),
        ),
        monthly=[_month(m, s, p, found.monthly_profit.get(m)) for m, s, p in found.monthly],
        channels=_channels(found.channels),
        by_company=_shares(found.by_company),
        trend=[_trend(t) for t in trend(session, companies, period.end)],
        summary=_summary(found.profit_loss, found.profit_loss_last_year),
        summary_reason=found.profit_loss_last_year.reason,
        top_customers=_top(top_customers(session, companies, period), found.monthly),
    )


def change_pct(now: Decimal | None, before: Decimal | None) -> Decimal | None:
    """The change against the comparison in percent, one decimal; None without a base."""
    if now is None or before is None or before == 0:
        return None
    return ((now - before) / abs(before) * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)


def percent_of(part: Decimal | None, whole: Decimal | None) -> Decimal | None:
    """The part as a percentage of the whole, one decimal; None without a whole."""
    if part is None or whole is None or whole == 0:
        return None
    return (part / whole * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)


def _decimal(value: int | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _difference(a: Figure, b: Figure) -> Figure:
    """a - b, this period and the comparison's, with the change."""
    value = a.value - b.value if a.value is not None and b.value is not None else None
    last = a.before - b.before if a.before is not None and b.before is not None else None
    return Figure(value=value, before=last, change_pct=change_pct(value, last))


def _profit_loss(now: StatementFigures, before: StatementFigures | None) -> ProfitLoss:
    def figure(key: str) -> Figure:
        value = now.values.get(key) if now.reason is None else None
        last = before.values.get(key) if before is not None and before.reason is None else None
        return Figure(value=value, before=last, change_pct=change_pct(value, last))

    def ratio(key: str) -> Ratio:
        value = percent_of(figures[key].value, figures["net_sales"].value)
        last = percent_of(figures[key].before, figures["net_sales"].before)
        change = value - last if value is not None and last is not None else None
        return Ratio(value=value, before=last, change_pts=change)

    figures = {key: figure(key) for key in PL_FIGURES}
    figures["other_costs"] = _difference(figures["gross_profit"], figures["net_profit"])
    ratios = {
        "gross_margin_pct": ratio("gross_profit"),
        "net_profit_pct": ratio("net_profit"),
        "cost_of_sales_pct": ratio("cost_of_sales"),
        "other_costs_pct": ratio("other_costs"),
    }
    return ProfitLoss(
        available=now.reason is None,
        reason=now.reason,
        as_of=now.as_of,
        shifted=now.shifted,
        cut=now.cut,
        before_reason=before.reason if before is not None else None,
        **figures,
        **ratios,
    )


def _month(
    month: date, sales: Decimal, purchases: Decimal, profit: StatementFigures | None
) -> MonthFigures:
    known = profit is not None and profit.reason is None
    return MonthFigures(
        month=month,
        sales=sales,
        purchases=purchases,
        gross_profit=profit.values.get("gross_profit") if known else None,
        net_profit=profit.values.get("net_profit") if known else None,
    )


def _balance_sheet(found: StatementFigures) -> BalanceSheet:
    values = {key: found.values.get(key) if found.reason is None else None for key in BS_FIGURES}
    return BalanceSheet(
        available=found.reason is None, reason=found.reason, as_of=found.as_of, **values
    )


def _channels(found: list[tuple[str, Decimal]]) -> list[Channel]:
    top = [Channel(name=name, net_sales=net) for name, net in found[:TOP_CHANNELS]]
    rest = sum((net for _, net in found[TOP_CHANNELS:]), Decimal(0))
    if len(found) > TOP_CHANNELS:
        top.append(Channel(name=OTHERS, net_sales=rest))
    return top


def _shares(found: list[tuple[int, Decimal]]) -> list[CompanyShare]:
    total = sum((net for _, net in found), Decimal(0))
    return [
        CompanyShare(
            company=entity,
            net_sales=net,
            share_pct=(net / total * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)
            if total
            else None,
        )
        for entity, net in sorted(found, key=lambda x: x[1], reverse=True)
    ]


SUMMARY = [
    # key, label, unit, higher is better
    ("net_sales", "Net sales", "amount", True),
    ("cost_of_sales", "Cost of sales", "amount", False),
    ("gross_profit", "Gross profit", "amount", True),
    ("gross_margin_pct", "Gross margin %", "percent", True),
    ("net_profit", "Net profit", "amount", True),
    ("net_profit_pct", "Net profit %", "percent", True),
]
PERCENTS = {"gross_margin_pct": "gross_profit", "net_profit_pct": "net_profit"}


def _summary(now: StatementFigures, last: StatementFigures) -> list[SummaryLine]:
    """The Profit & Loss summary against last year (F-OVR-003): the period's and last year's
    figures, the change in percent, or in points for a percentage."""

    def figures(found: StatementFigures) -> dict[str, Decimal | None]:
        values: dict[str, Decimal | None] = {
            key: found.values.get(key) if found.reason is None else None for key in PL_FIGURES
        }
        for key, part in PERCENTS.items():
            values[key] = percent_of(values[part], values["net_sales"])
        return values

    current, before = figures(now), figures(last)
    found = []
    for key, label, unit, higher in SUMMARY:
        value, last_value = current[key], before[key]
        points = value - last_value if value is not None and last_value is not None else None
        found.append(
            SummaryLine(
                key=key, label=label, unit=unit, higher_is_better=higher,
                value=value, last_year=last_value,
                change_pct=change_pct(value, last_value) if unit == "amount" else None,
                change_pts=points if unit == "percent" else None,
            )
        )  # fmt: skip
    return found


def _trend(t: TrendMonth) -> TrendOut:
    return TrendOut(
        month=t.month,
        net_sales=t.net_sales,
        gross_profit=t.gross_profit,
        net_profit=t.net_profit,
        cash_and_bank=t.cash_and_bank,
        customers=t.customers,
    )


def _top(
    found: list[TopCustomer], monthly: list[tuple[date, Decimal, Decimal]]
) -> list[TopCustomerOut]:
    total = sum((sales for _, sales, _ in monthly), Decimal(0))
    customers = []
    for customer in found:
        payment_status = party_payment_status(
            customer.balance, customer.overdue, customer.pending, customer.advance
        )
        customers.append(
            TopCustomerOut(
                party_id=customer.party_id,
                name=customer.name,
                net_sales=customer.net_sales,
                share_pct=percent_of(customer.net_sales, total),
                balance=customer.balance,
                overdue=customer.overdue,
                status="overdue" if payment_status == "overdue" else "current",
                payment_status=payment_status,
            )
        )
    return customers
