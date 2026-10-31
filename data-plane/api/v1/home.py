"""`GET /api/v1/home`: the dashboard home's figures (D1; docs/design/dashboard.md Section 0.1).

For any combination of the companies the caller may see (`company`, repeatable; default all,
added together: combined, without inter-company eliminations) and a period: whole months
(`month=2026-04`, repeatable, adjacent or not) or a date range (`date_from`, `date_to`).
`compare=true` adds last year's Profit & Loss for the same months or dates. The figures and
how they are found: core/home.py; periods and statement windows: core/report_periods.py.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.access import CurrentAccess
from api.v1.common import ReportSession
from core.home import BS_FIGURES, PL_FIGURES, StatementFigures, home
from core.report_periods import Period

router = APIRouter(tags=["home"])

MAX_MONTHS = 36
MAX_DAYS = 3 * 366
TOP_CHANNELS = 4  # the largest voucher types; the rest are "Others"
OTHERS = "Others"


class Figure(BaseModel):
    value: Decimal | None
    last_year: Decimal | None = None
    change_pct: Decimal | None = None  # against last year, one decimal; None without one


class ProfitLoss(BaseModel):
    available: bool
    reason: str | None  # why the figures aren't available
    as_of: date | None  # the last statement date used
    shifted: bool  # a month ran to a later stored date (the source's Educational mode)
    last_year_reason: str | None
    net_sales: Figure
    cost_of_sales: Figure
    gross_profit: Figure
    net_profit: Figure


class BalanceSheet(BaseModel):
    available: bool
    reason: str | None
    as_of: date | None
    total_assets: Decimal | None
    current_assets: Decimal | None
    current_liabilities: Decimal | None
    capital_and_reserves: Decimal | None


class Balances(BaseModel):
    as_of: date
    cash_and_bank: Decimal
    receivables: Decimal
    payables: Decimal
    stock_value: Decimal | None  # the source's, stored with the statements
    stock_value_as_of: date | None


class MonthFigures(BaseModel):
    month: date
    sales: Decimal
    purchases: Decimal


class Channel(BaseModel):
    name: str  # a voucher type's name, or "Others"
    net_sales: Decimal


class CompanyShare(BaseModel):
    company: int
    net_sales: Decimal
    share_pct: Decimal | None  # of the selection's net sales, one decimal


class PeriodOut(BaseModel):
    start: date
    end: date
    months: list[date]  # first days; empty for a date range


class Home(BaseModel):
    companies: list[int]
    combined: bool  # several companies added together, without inter-company eliminations
    period: PeriodOut
    profit_loss: ProfitLoss
    balance_sheet: BalanceSheet
    balances: Balances
    monthly: list[MonthFigures]
    channels: list[Channel]
    by_company: list[CompanyShare]


@router.get("/home")
def dashboard_home(
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
    compare: bool = False,
) -> Home:
    companies = access.entities(company)
    period = _period(month, date_from, date_to)
    found = home(session, companies, period, compare)
    return Home(
        companies=companies,
        combined=len(companies) > 1,
        period=PeriodOut(start=period.start, end=period.end, months=list(period.months)),
        profit_loss=_profit_loss(found.profit_loss, found.profit_loss_last_year),
        balance_sheet=_balance_sheet(found.balance_sheet),
        balances=Balances(
            as_of=period.end,
            cash_and_bank=found.cash_and_bank,
            receivables=found.receivables,
            payables=found.payables,
            stock_value=found.stock_value,
            stock_value_as_of=found.profit_loss.as_of if found.stock_value is not None else None,
        ),
        monthly=[MonthFigures(month=m, sales=s, purchases=p) for m, s, p in found.monthly],
        channels=_channels(found.channels),
        by_company=_shares(found.by_company),
    )


def _period(months: list[str] | None, start: date | None, end: date | None) -> Period:
    """Whole months, or a date range: exactly one of them."""
    if months:
        if start or end:
            raise HTTPException(422, "Give months or a date range, not both.")
        if len(months) > MAX_MONTHS:
            raise HTTPException(422, f"At most {MAX_MONTHS} months.")
        try:
            firsts = [date.fromisoformat(f"{m}-01") for m in months]
        except ValueError:
            raise HTTPException(422, "Months are written YYYY-MM.") from None
        if any(len(m) != 7 for m in months):
            raise HTTPException(422, "Months are written YYYY-MM.")
        return Period.of_months(firsts)
    if start is None or end is None:
        raise HTTPException(422, "Give months (month=YYYY-MM) or date_from and date_to.")
    if end < start or (end - start).days > MAX_DAYS:
        raise HTTPException(422, "date_to must follow date_from, at most three years later.")
    return Period(start, end)


def change_pct(now: Decimal | None, before: Decimal | None) -> Decimal | None:
    """The change against last year in percent, one decimal; None without a base."""
    if now is None or before is None or before == 0:
        return None
    return ((now - before) / abs(before) * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)


def _profit_loss(now: StatementFigures, before: StatementFigures | None) -> ProfitLoss:
    def figure(key: str) -> Figure:
        value = now.values.get(key) if now.reason is None else None
        last = before.values.get(key) if before is not None and before.reason is None else None
        return Figure(value=value, last_year=last, change_pct=change_pct(value, last))

    figures = {key: figure(key) for key in PL_FIGURES}
    return ProfitLoss(
        available=now.reason is None,
        reason=now.reason,
        as_of=now.as_of,
        shifted=now.shifted,
        last_year_reason=before.reason if before is not None else None,
        **figures,
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
