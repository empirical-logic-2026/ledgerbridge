"""`GET /api/v1/reports/profit-loss`: the Profit & Loss report page (D1 c1; screen 6).

The selected companies (default all, combined, without inter-company eliminations) and a
period (whole months or a date range), viewed company by company, month by month or quarter
by quarter, always with a total; `compare` adds the previous period or last year
(api/v1/common.py) as the `before` column, and the change. Each line's
amounts per column, the same as a percentage of net sales, and whether the source's own
statements match ours for the companies and dates used. How: core/statement_report.py.
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from api.access import CurrentAccess
from api.v1.common import (
    ComparedWith,
    CompareParam,
    ReportSession,
    SpanParam,
    compared_with,
    formula,
    parse_period,
)
from api.v1.company_display import display_company_name
from api.v1.home import change_pct
from core.balance_sheet import balance_sheet
from core.models import accounting as A  # noqa: N812
from core.profit_loss_tally import TOTAL, tally_profit_loss
from core.profit_loss_tally import drill as pl_drill
from core.ratios import ASSET_PARTS, BORROWING_PARTS, LIABILITY_PARTS, Position
from core.statement_report import percent, profit_loss

router = APIRouter(prefix="/reports", tags=["reports"])


class ColumnOut(BaseModel):
    key: str
    label: str
    kind: Literal["company", "month", "quarter", "total", "before"]


class LineOut(BaseModel):
    key: str
    label: str
    level: Literal["main", "sub", "detail"]
    section: str | None
    higher_is_better: bool  # income, profit, closing stock; else a cost
    values: dict[str, Decimal | None] = formula(
        "F-PL-007"
    )  # column key -> amount; None: not available
    pct_of_sales: dict[str, Decimal | None] = formula(
        "F-PL-008"
    )  # column key -> % of that column's net sales
    change_pct: Decimal | None = formula("F-CMP-001")  # total against the `before` column


class MatchingOut(BaseModel):
    matches: bool  # every company and date used compared, and every line and total equal
    dates: list[date]  # the statement dates the figures come from
    differing: int = formula("F-CHK-001")  # compared lines and totals that differ
    compared: int = formula("F-CHK-002")
    unchecked: int = formula(
        "F-CHK-003"
    )  # company x date pairs without the source's statement to compare


class StatementReport(BaseModel):
    companies: list[int]
    combined: bool
    view: Literal["company", "month", "quarter"]
    period_start: date
    period_end: date
    compared_with: ComparedWith | None
    columns: list[ColumnOut]
    lines: list[LineOut]
    reason: str | None  # why there are no figures
    shifted: bool  # a month ran to a later stored date (the source's Educational mode)
    before_reason: str | None  # why the comparison period has no figures
    matching: MatchingOut


@router.get("/profit-loss")
def profit_loss_report(
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
    view: Literal["company", "month", "quarter"] = "company",
    compare: CompareParam | None = None,
    span: SpanParam | None = None,
) -> StatementReport:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    before, described = compared_with(period, compare, span)
    label = described.label if described else ""
    found = profit_loss(session, companies, period, view, before, label)
    lines = [
        LineOut(
            key=line.key,
            label=line.label,
            level=line.level,
            section=line.section,
            higher_is_better=line.earned,
            values=line.values,
            pct_of_sales={c: percent(v, found.net_sales.get(c)) for c, v in line.values.items()},
            change_pct=change_pct(line.values.get("total"), line.values.get("before")),
        )
        for line in found.lines
    ]
    m = found.matching
    return StatementReport(
        companies=companies,
        combined=len(companies) > 1,
        view=view,
        period_start=period.start,
        period_end=period.end,
        compared_with=described,
        columns=[
            ColumnOut(
                key=c.key,
                label=display_company_name(c.label) if c.kind == "company" else c.label,
                kind=c.kind,
            )
            for c in found.columns
        ],
        lines=lines,
        reason=found.reason,
        shifted=found.shifted,
        before_reason=found.before_reason,
        matching=MatchingOut(
            matches=m.matches,
            dates=m.dates,
            differing=m.differing,
            compared=m.compared,
            unchecked=m.unchecked,
        ),
    )


# --- the Balance Sheet (RPT-003, RPT-014) ---------------------------------------------------

RATIO_FORMULAS = {
    "current_ratio": "F-RAT-008",
    "quick_ratio": "F-RAT-009",
    "debt_to_equity": "F-RAT-010",
    "receivable_days": "F-RAT-004",
    "payable_days": "F-RAT-005",
    "inventory_days": "F-RAT-006",
    "working_capital_days": "F-RAT-007",
}


class SheetLineOut(BaseModel):
    key: str
    label: str
    level: Literal["main", "sub", "detail"]
    section: Literal["assets", "liabilities"]
    value: Decimal | None = formula("F-BS-005")
    before: Decimal | None = formula("F-BS-005")
    change_pct: Decimal | None = formula("F-CMP-001")


class SheetTotalOut(BaseModel):
    section: Literal["assets", "liabilities"]
    value: Decimal | None = formula("F-BS-006")
    before: Decimal | None = formula("F-BS-006")
    change_pct: Decimal | None = formula("F-CMP-001")


class RatioPartOut(BaseModel):
    """One part of current assets, current liabilities or borrowings (a line of the hover)."""

    key: str
    label: str
    amount: Decimal = formula("F-BS-010")


class RatioBasisOut(BaseModel):
    """What a ratio is worked out from at the date, so anyone can check it (core/ratios.py)."""

    current_assets: Decimal = formula("F-BS-007")
    current_liabilities: Decimal = formula("F-BS-008")
    borrowings: Decimal = formula("F-BS-009")
    stock: Decimal = formula("F-BAL-005")
    equity: Decimal | None = formula("F-BS-004")
    asset_parts: list[RatioPartOut]
    liability_parts: list[RatioPartOut]
    borrowing_parts: list[RatioPartOut]
    marked_short_term: int = formula("F-BS-011")  # ledgers marked as short-term borrowings
    combined: bool  # several companies added up, without inter-company eliminations


class RatioOut(BaseModel):
    key: str
    label: str
    unit: Literal["times", "days"]
    formula_id: str  # the ratio's own formula (F-RAT-004 ...)
    value: Decimal | None = formula("F-RAT-000")
    before: Decimal | None = formula("F-RAT-000")
    change: Decimal | None = formula("F-RAT-000")  # in the ratio's own unit
    basis: RatioBasisOut | None = None  # current, quick and debt to equity: their parts


class BalanceSheetReport(BaseModel):
    companies: list[int]
    combined: bool
    period_start: date
    period_end: date
    as_of: date | None  # the date the figures are at
    before_as_of: date | None
    compared_with: ComparedWith | None
    reason: str | None
    before_reason: str | None
    lines: list[SheetLineOut]
    totals: list[SheetTotalOut]
    ratios: list[RatioOut]


def _parts(amounts: dict[str, Decimal], labels: dict[str, str]) -> list[RatioPartOut]:
    """The parts with an amount, in the order of `labels`."""
    return [
        RatioPartOut(key=key, label=label, amount=amounts[key])
        for key, label in labels.items()
        if amounts.get(key)
    ]


def _basis(found: Position | None, combined: bool) -> RatioBasisOut | None:
    if found is None:
        return None
    return RatioBasisOut(
        current_assets=found.current_assets,
        current_liabilities=found.current_liabilities,
        borrowings=found.total_borrowings,
        stock=found.stock,
        equity=found.equity,
        asset_parts=_parts(found.assets, ASSET_PARTS),
        liability_parts=_parts(found.liabilities, LIABILITY_PARTS),
        borrowing_parts=_parts(found.borrowings, BORROWING_PARTS),
        marked_short_term=found.marked,
        combined=combined,
    )


@router.get("/balance-sheet")
def balance_sheet_report(
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
    compare: CompareParam | None = None,
    span: SpanParam | None = None,
) -> BalanceSheetReport:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    before, described = compared_with(period, compare, span)
    found = balance_sheet(session, companies, period, before)

    def change(now: Decimal | None, last: Decimal | None) -> Decimal | None:
        return now - last if now is not None and last is not None else None

    return BalanceSheetReport(
        companies=companies,
        combined=len(companies) > 1,
        period_start=period.start,
        period_end=period.end,
        as_of=found.as_of,
        before_as_of=found.before_as_of,
        compared_with=described,
        reason=found.reason,
        before_reason=found.before_reason,
        lines=[
            SheetLineOut(
                key=line.key, label=line.label, level=line.level, section=line.section,
                value=line.values.get("now"), before=line.values.get("before"),
                change_pct=change_pct(line.values.get("now"), line.values.get("before")),
            )
            for line in found.lines
        ],
        totals=[
            SheetTotalOut(
                section=section, value=values.get("now"), before=values.get("before"),
                change_pct=change_pct(values.get("now"), values.get("before")),
            )
            for section, values in found.totals.items()
        ],
        ratios=[
            RatioOut(
                key=r.key, label=r.label, unit=r.unit, formula_id=RATIO_FORMULAS[r.key],
                value=r.values.get("now"), before=r.values.get("before"),
                change=change(r.values.get("now"), r.values.get("before")),
                basis=_basis(r.positions.get("now"), len(companies) > 1),
            )
            for r in found.ratios
        ],
    )  # fmt: skip


# --- the Profit & Loss in Tally's layout (ADR-056) ------------------------------------------


class TallyRowOut(BaseModel):
    key: str
    label: str
    kind: Literal["group", "stock", "gross_carried", "gross_brought", "net_result"]
    values: dict[str, Decimal | None] = formula("F-PL-011")  # column -> amount; None: blank
    group: str | None  # the group's key: opens its drill-down


class TallySideOut(BaseModel):
    rows: list[TallyRowOut]
    total: dict[str, Decimal] = formula("F-PL-013")  # the gross subtotal, or the net Total


class TallyBlockOut(BaseModel):
    left: TallySideOut
    right: TallySideOut


class TallyColumnOut(BaseModel):
    key: str  # "company:3", "total"
    label: str


class TallyProfitLossOut(BaseModel):
    companies: list[int]
    combined: bool
    period_start: date  # as asked
    period_end: date
    start: date | None  # the period shown (statement dates)
    end: date | None
    columns: list[TallyColumnOut]
    gross: TallyBlockOut | None
    net: TallyBlockOut | None
    gross_profit: dict[str, Decimal] = formula("F-PL-012")  # a loss negative
    net_profit: dict[str, Decimal] = formula("F-PL-014")
    reason: str | None  # why there are no figures
    nearest: list[date]  # stored statement dates around the end asked for


class TallyDrillRowOut(BaseModel):
    key: str
    label: str
    kind: Literal["group", "ledger"]
    depth: int
    parent: str | None
    amount: Decimal = formula("F-PL-016")
    ledger_id: int | None
    company: int | None


class TallyDrillOut(BaseModel):
    rows: list[TallyDrillRowOut]
    reason: str | None


def _side_out(side: object) -> TallySideOut:
    return TallySideOut(
        rows=[
            TallyRowOut(key=r.key, label=r.label, kind=r.kind, values=r.values, group=r.group)
            for r in side.rows  # type: ignore[attr-defined]
        ],
        total=side.total,  # type: ignore[attr-defined]
    )


@router.get("/profit-loss/tally")
def profit_loss_tally(
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
) -> TallyProfitLossOut:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    found = tally_profit_loss(session, companies, period)
    rows = session.execute(select(A.Entity.id, A.Entity.name).where(A.Entity.id.in_(companies)))
    names = {entity: name for entity, name in rows}
    columns = [
        TallyColumnOut(
            key=c,
            label="Total"
            if c == TOTAL
            else display_company_name(names.get(int(c.split(":")[1]), c)),
        )
        for c in found.columns
    ]
    shown = found.end is not None
    return TallyProfitLossOut(
        companies=companies, combined=len(companies) > 1, period_start=period.start,
        period_end=period.end, start=found.start, end=found.end, columns=columns,
        gross=TallyBlockOut(left=_side_out(found.gross.left), right=_side_out(found.gross.right))
        if shown else None,
        net=TallyBlockOut(left=_side_out(found.net.left), right=_side_out(found.net.right))
        if shown else None,
        gross_profit=found.gross_profit, net_profit=found.net_profit, reason=found.reason,
        nearest=found.nearest,
    )  # fmt: skip


@router.get("/profit-loss/drill")
def profit_loss_drill(
    session: ReportSession,
    access: CurrentAccess,
    group: str = Query(max_length=255),
    side: Literal["left", "right"] = "left",
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
) -> TallyDrillOut:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    rows, reason = pl_drill(session, companies, period, group, side)
    return TallyDrillOut(
        rows=[
            TallyDrillRowOut(
                key=r.key, label=r.label, kind=r.kind, depth=r.depth, parent=r.parent,
                amount=r.amount, ledger_id=r.ledger_id, company=r.company,
            )
            for r in rows
            if r.amount or r.depth == 0
        ],
        reason=reason,
    )  # fmt: skip
