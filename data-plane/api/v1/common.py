"""What every `/api/v1` module shares: the read-only session (report_ro, ADR-049) and the
period a report is asked for (whole months or a date range: core/report_periods.py)."""

from datetime import date
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from api.deps import get_report_session
from core.report_periods import Period

ReportSession = Annotated[Session, Depends(get_report_session)]

MAX_MONTHS = 36
MAX_DAYS = 3 * 366


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
