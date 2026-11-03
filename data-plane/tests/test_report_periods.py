"""The period a report covers (RPT-016; formula F-CMP-002): the previous period for MTD, QTD,
YTD, FY and periods chosen by hand, month ends and leap years, and where a date range's
statement figures end (the last stored date within it)."""

from datetime import date

import pytest

from core.report_periods import Period, months_earlier, windows


@pytest.mark.parametrize(
    ("on", "months", "expected"),
    [
        (date(2026, 11, 2), 1, date(2026, 10, 2)),
        (date(2026, 5, 31), 1, date(2026, 4, 30)),  # a month end stays a month end
        (date(2026, 4, 30), 1, date(2026, 3, 31)),
        (date(2026, 3, 30), 1, date(2026, 2, 28)),  # no 30-Feb: its last day
        (date(2024, 5, 29), 3, date(2024, 2, 29)),  # a leap year
        (date(2026, 1, 15), 3, date(2025, 10, 15)),  # across a year
    ],
)
def test_the_same_day_months_earlier(on: date, months: int, expected: date) -> None:
    assert months_earlier(on, months) == expected


def test_month_to_date_is_compared_with_the_same_days_of_the_month_before() -> None:
    mtd = Period(date(2026, 11, 1), date(2026, 11, 2))
    assert mtd.previous("month") == Period(date(2026, 10, 1), date(2026, 10, 2))


def test_quarter_to_date_is_compared_with_the_same_days_of_the_quarter_before() -> None:
    qtd = Period(date(2026, 10, 1), date(2026, 11, 2))
    assert qtd.previous("quarter") == Period(date(2026, 7, 1), date(2026, 8, 2))


def test_year_to_date_and_a_financial_year_are_compared_with_a_year_earlier() -> None:
    ytd = Period(date(2026, 4, 1), date(2026, 11, 2))
    assert ytd.previous("year") == Period(date(2025, 4, 1), date(2025, 11, 2))
    fy = Period.of_months([date(2026, m, 1) for m in range(4, 13)] + [date(2027, 1, 1)])
    assert fy.previous("year") == fy.last_year()
    leap = Period(date(2024, 2, 1), date(2024, 2, 29))
    assert leap.previous("year") == Period(date(2023, 2, 1), date(2023, 2, 28))


def test_months_chosen_by_hand_are_compared_with_as_many_months_just_before() -> None:
    chosen = Period.of_months([date(2026, 5, 1), date(2026, 6, 1)])
    assert chosen.previous() == Period.of_months([date(2026, 3, 1), date(2026, 4, 1)])
    apart = Period.of_months([date(2026, 4, 1), date(2026, 6, 1)])  # three months spanned
    assert apart.previous().months == (date(2026, 1, 1), date(2026, 3, 1))


def test_dates_chosen_by_hand_are_compared_with_as_many_days_just_before() -> None:
    chosen = Period(date(2026, 4, 11), date(2026, 4, 20))
    assert chosen.previous() == Period(date(2026, 4, 1), date(2026, 4, 10))


def test_compared_takes_the_kind() -> None:
    mtd = Period(date(2026, 11, 1), date(2026, 11, 2))
    assert mtd.compared("previous", "month") == mtd.previous("month")
    assert mtd.compared("last_year", "month") == mtd.last_year()


STORED = {date(2026, 3, 31), date(2026, 4, 30), date(2026, 5, 31), date(2026, 6, 30)}


def test_a_range_runs_to_the_last_stored_date_within_it() -> None:
    found = windows(Period(date(2026, 4, 1), date(2026, 6, 15)), STORED, date(2025, 4, 1))
    assert found.pairs == [(date(2026, 3, 31), date(2026, 5, 31))] and found.cut


def test_a_range_on_stored_dates_is_not_cut() -> None:
    found = windows(Period(date(2026, 4, 1), date(2026, 6, 30)), STORED, date(2025, 4, 1))
    assert found.pairs == [(date(2026, 3, 31), date(2026, 6, 30))] and not found.cut


def test_a_range_without_a_stored_date_has_no_profit() -> None:
    found = windows(Period(date(2026, 7, 1), date(2026, 7, 2)), STORED, date(2025, 4, 1))
    assert not found.available
    assert "no statement is stored between 01-Jul-2026 and 02-Jul-2026" in str(found.reason)
