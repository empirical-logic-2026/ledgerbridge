"""What every `/api/v1` module shares: the read-only session (report_ro, ADR-049), the
period a report is asked for (whole months or a date range: core/report_periods.py) and the
period it is compared with (RPT-016; formula F-CMP-002).

`compare`: `previous` (the period just before; `span` says what a "to date" period runs
over: `month` for MTD, `quarter` for QTD, `year` for YTD and FY), `last_year`, or `none`.
`true` and `false`, from links made before the previous period existed, mean last year and
none.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from pydantic_core import PydanticUndefined
from sqlalchemy.orm import Session

from api.deps import get_report_session
from core.report_periods import Period

ReportSession = Annotated[Session, Depends(get_report_session)]

MAX_MONTHS = 36
MAX_DAYS = 3 * 366
CompareParam = Literal["previous", "last_year", "none", "true", "false"]
SpanParam = Literal["month", "quarter", "year"]
LABELS = {"previous": "Previous period", "last_year": "Last year"}


def formula(formula_id: str, default: Any = PydanticUndefined) -> Any:  # noqa: ANN401
    """A response field showing a figure, with its formula's ID in docs/formula-sheet.md (RPT-015;
    `tests/test_formulas.py` checks that every figure has one and that the ID exists)."""
    return Field(default, json_schema_extra={"formula": formula_id})


class Comparable(BaseModel):
    """A figure with the comparison period's: `value` and `before` follow the formula of the
    field that holds it; the change has its own (F-CMP-001, or F-CMP-003 in points)."""

    value: Decimal | int | None
    before: Decimal | int | None = None


class ComparedWith(BaseModel):
    """The period the figures' `before` values come from."""

    kind: Literal["previous", "last_year"]
    label: str  # "Previous period", "Last year"
    start: date
    end: date
    months: list[date]  # first days; empty for a date range


def compared_with(
    period: Period, compare: CompareParam | None, span: SpanParam | None
) -> tuple[Period | None, ComparedWith | None]:
    """The comparison period asked for, and its description; (None, None) for none."""
    kind = {"true": "last_year", "false": None, "none": None}.get(compare or "none", compare)
    if kind is None:
        return None, None
    before = period.compared(kind, span)
    return before, ComparedWith(
        kind=kind, label=LABELS[kind], start=before.start, end=before.end,
        months=list(before.months),
    )  # fmt: skip


def parse_period(months: list[str] | None, start: date | None, end: date | None) -> Period:
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
