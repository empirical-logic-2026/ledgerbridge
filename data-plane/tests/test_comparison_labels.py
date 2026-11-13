"""How the comparison is named and dated in every response (F-CMP-002; ADR-057): "Previous
period" or "Last year" with its dates; for a year to date or a financial year, the previous
period is the same dates a year earlier and says so (option (a), 2026-11-12)."""

from datetime import date

from api.v1.common import compared_with, last_year_of
from core.report_periods import Period


def test_each_period_toggle_names_and_dates_its_comparison() -> None:
    month_to_date = Period(date(2026, 11, 1), date(2026, 11, 13))
    _, found = compared_with(month_to_date, "previous", "month")
    assert (found.label, found.start, found.end) == (
        "Previous period", date(2026, 10, 1), date(2026, 10, 13)
    )  # fmt: skip
    quarter = Period(date(2026, 10, 1), date(2026, 11, 13))
    _, found = compared_with(quarter, "previous", "quarter")
    assert (found.label, found.start) == ("Previous period", date(2026, 7, 1))
    year_to_date = Period(date(2026, 4, 1), date(2026, 11, 13))
    _, found = compared_with(year_to_date, "previous", "year")
    assert found.label == "Previous period (same dates last year)"
    assert (found.start, found.end) == (date(2025, 4, 1), date(2025, 11, 13))
    _, found = compared_with(year_to_date, "last_year", None)
    assert found.label == "Last year"
    months = Period.of_months([date(2026, 8, 1), date(2026, 9, 1)])
    _, found = compared_with(months, "previous", None)
    assert (found.label, found.months) == ("Previous period", [date(2026, 6, 1), date(2026, 7, 1)])
    assert compared_with(months, "none", None) == (None, None)


def test_the_overview_summary_is_always_last_year_with_its_dates() -> None:
    found = last_year_of(Period(date(2026, 4, 1), date(2026, 11, 13)))
    assert (found.label, found.start, found.end) == (
        "Last year", date(2025, 4, 1), date(2025, 11, 13)
    )  # fmt: skip
