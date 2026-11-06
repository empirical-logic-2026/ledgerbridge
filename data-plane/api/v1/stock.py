"""`GET /api/v1/stock` and `.../{item_id}`: the Stock page and one item's page (RPT-014). For
any combination of the companies the caller may see (`company`, repeatable; default all,
combined) and a period (`month`, repeatable, or `date_from` and `date_to`). An item is known by
its name across those companies; one outside them is 404, like a company outside access.
Quantities are ours, values the source's own at the last stored date within the period. How:
core/stock.py.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.access import CurrentAccess
from api.v1.common import ReportSession, formula, parse_period
from api.v1.home import PeriodOut
from core.stock import ItemRow, find_item, item_page, stock_summary

router = APIRouter(prefix="/stock", tags=["stock"])


class StockItemOut(BaseModel):
    item_id: int
    name: str
    group: str | None
    unit: str | None
    companies: list[int]
    opening: Decimal = formula("F-STK-001")
    inward: Decimal = formula("F-STK-002")
    outward: Decimal = formula("F-STK-003")
    closing: Decimal = formula("F-STK-004")
    value: Decimal | None = formula("F-STK-005")  # None: the source's not stored for the date
    rate: Decimal | None = formula("F-STK-006")


class StockNamedValue(BaseModel):
    name: str
    value: Decimal = formula("F-STK-005")


class StockDatedValue(BaseModel):
    date: date
    value: Decimal = formula("F-STK-007")


class StockOut(BaseModel):
    companies: list[int]
    combined: bool
    period: PeriodOut
    value_on: date | None  # the last stored date within the period: values are at it
    total_value: Decimal | None = formula("F-STK-007")
    items: list[StockItemOut]
    by_group: list[StockNamedValue]  # top-level stock groups
    by_godown: list[StockNamedValue]  # top-level godowns
    by_date: list[StockDatedValue]  # the stock value at the last stored dates


class StockMovementOut(BaseModel):
    company: int
    date: date
    voucher_id: int
    voucher_number: str
    voucher_type: str
    godown: str | None
    quantity: Decimal = formula("F-STK-002")  # signed: in +, out -
    balance: Decimal = formula("F-STK-004")  # the quantity after it
    amount: Decimal = formula("F-STK-008")


class StockItemMonthOut(BaseModel):
    month: date
    inward: Decimal = formula("F-STK-002")
    outward: Decimal = formula("F-STK-003")
    closing: Decimal = formula("F-STK-004")
    value: Decimal | None = formula("F-STK-005")


class StockItemPageOut(BaseModel):
    item: StockItemOut
    period: PeriodOut
    value_on: date | None
    movements: list[StockMovementOut]
    truncated: bool  # more movements than shown
    months: list[StockItemMonthOut]


def _item(row: ItemRow) -> StockItemOut:
    return StockItemOut(
        item_id=row.item_id, name=row.name, group=row.group, unit=row.unit,
        companies=row.companies, opening=row.opening, inward=row.inward, outward=row.outward,
        closing=row.closing, value=row.value, rate=row.rate,
    )  # fmt: skip


@router.get("")
def stock(
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
) -> StockOut:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    summary = stock_summary(session, companies, period)
    return StockOut(
        companies=companies,
        combined=len(companies) > 1,
        period=PeriodOut(start=period.start, end=period.end, months=list(period.months)),
        value_on=summary.value_on,
        total_value=summary.total_value,
        items=[_item(row) for row in summary.items],
        by_group=[StockNamedValue(name=n, value=v) for n, v in summary.by_group],
        by_godown=[StockNamedValue(name=n, value=v) for n, v in summary.by_godown],
        by_date=[StockDatedValue(date=d, value=v) for d, v in summary.by_date],
    )


@router.get("/{item_id}")
def item(
    item_id: int,
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
) -> StockItemPageOut:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    ref = find_item(session, companies, item_id)
    if ref is None:
        raise HTTPException(404, "No such stock item in the selected companies.")
    page = item_page(session, companies, ref, period)
    return StockItemPageOut(
        item=_item(page.item),
        period=PeriodOut(start=period.start, end=period.end, months=list(period.months)),
        value_on=page.value_on,
        movements=[
            StockMovementOut(
                company=m.company, date=m.on, voucher_id=m.voucher_id,
                voucher_number=m.voucher_number, voucher_type=m.voucher_type, godown=m.godown,
                quantity=m.quantity, balance=m.balance, amount=m.amount,
            )
            for m in page.movements
        ],
        truncated=page.truncated,
        months=[
            StockItemMonthOut(
                month=m.month, inward=m.inward, outward=m.outward, closing=m.closing,
                value=m.value,
            )
            for m in page.months
        ],
    )  # fmt: skip
