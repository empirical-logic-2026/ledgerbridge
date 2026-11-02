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
from api.v1.home import change_pct
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
        columns=[ColumnOut(key=c.key, label=c.label, kind=c.kind) for c in found.columns],
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
