"""The period a report covers, and the stored statements its profit is taken from (D1;
RPT-008, docs/design/dashboard.md Section 0.1).

A period is either **whole months** (one or several, adjacent or not) or a **from/to date
range**. Figures from the entries (sales, purchases, balances) work for any period. Figures
from the stored statements (`statement_lines`, validated against the source's own) need a
statement at the period's end and one just before its start, because a stored Profit & Loss
runs from the books' beginning: a period's figure is the one at its end less the one before
it (nothing before the books' first day).

- **Months:** each month ends at its last day, or, where the source's statements exist only
  for some days (Tally's Educational mode: the 1st, 2nd and 31st), at the first stored date
  up to two days later (a 30-day month then runs to the 2nd of the next month: `shifted`).
- **Date ranges** (MTD, QTD, YTD and dates chosen; RPT-016): the statement the day before
  the start date must be stored (or the range starts at the books' beginning). The figures
  run to the end date when its statement is stored, else to the **last stored date within
  the range** (`Windows.cut`: "to 31-Oct-2026"); with none, profit isn't available, with the
  reason.
- **Compared with** (`Period.compared`, formula F-CMP-002): the previous period or last year.
  The previous period of a month (MTD) is the same days of the month before, of a quarter
  (QTD) the same days of the quarter before; a year to date (YTD) and a financial year (FY)
  are compared with the same dates a year earlier. Other months: the same number of months
  just before; other dates: the same number of days just before.
"""

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import accounting as A  # noqa: N812
from core.models.reporting import StatementLine

MONTH_END_SLACK = timedelta(days=2)  # a month's statement may be stored up to 2 days late
SPANS = {"month": 1, "quarter": 3}  # a "to date" period's span in months (MTD, QTD)
YEAR = "year"  # YTD and FY: compared with the same dates a year earlier
COMPARISONS = ("previous", "last_year")


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    months: tuple[date, ...] = ()  # first days of the chosen months; () for a date range

    @classmethod
    def of_months(cls, months: list[date]) -> "Period":
        firsts = tuple(sorted({m.replace(day=1) for m in months}))
        return cls(firsts[0], last_day(firsts[-1]), firsts)

    def last_year(self) -> "Period":
        if self.months:
            return Period.of_months([year_earlier(m) for m in self.months])
        return Period(year_earlier(self.start), year_earlier(self.end))

    def previous(self, span: str | None = None) -> "Period":
        """The period just before: by the span the period runs over ("month", "quarter",
        "year"), else the same number of months, or of days, just before."""
        if span == YEAR:
            return self.last_year()
        if span in SPANS:
            return self.shifted(SPANS[span])
        if self.months:
            first, last = self.months[0], self.months[-1]
            return self.shifted((last.year - first.year) * 12 + last.month - first.month + 1)
        days = (self.end - self.start).days + 1
        return Period(self.start - timedelta(days=days), self.start - timedelta(days=1))

    def shifted(self, months: int) -> "Period":
        """The same months, or the same days, `months` months earlier."""
        if self.months:
            return Period.of_months([months_earlier(m, months) for m in self.months])
        return Period(months_earlier(self.start, months), months_earlier(self.end, months))

    def compared(self, kind: str, span: str | None = None) -> "Period":
        """The period this one is compared with: "previous" or "last_year"."""
        return self.previous(span) if kind == "previous" else self.last_year()

    def month_starts(self) -> list[date]:
        """The months the period touches (all of them, for a range)."""
        if self.months:
            return list(self.months)
        found, month = [], self.start.replace(day=1)
        while month <= self.end:
            found.append(month)
            month = last_day(month) + timedelta(days=1)
        return found


@dataclass
class Windows:
    """Where a period's statement figures come from: (date before, end date) pairs; the
    date before is None at the books' beginning (nothing to deduct)."""

    pairs: list[tuple[date | None, date]] = field(default_factory=list)
    shifted: bool = False  # some month ends on a later stored date (Educational mode)
    reason: str | None = None  # why there are none
    cut: bool = False  # a date range's figures end at the last stored date before its end

    @property
    def available(self) -> bool:
        return self.reason is None and bool(self.pairs)

    @property
    def end(self) -> date | None:
        return self.pairs[-1][1] if self.pairs else None


def last_day(month: date) -> date:
    return month.replace(day=calendar.monthrange(month.year, month.month)[1])


def months_earlier(on: date, months: int) -> date:
    """The same day `months` months earlier: a month's last day stays its last day, and a
    day the earlier month hasn't becomes its last day (31-May -> 30-Apr, 29-Feb -> 28-Feb)."""
    index = on.year * 12 + on.month - 1 - months
    target = date(index // 12, index % 12 + 1, 1)
    if on == last_day(on):
        return last_day(target)
    return target.replace(day=min(on.day, last_day(target).day))


def year_earlier(on: date) -> date:
    day = min(on.day, calendar.monthrange(on.year - 1, on.month)[1])
    return on.replace(year=on.year - 1, day=day)


def stored_dates(session: Session, companies: list[int]) -> set[date]:
    """The dates every one of the companies has our statements stored for."""
    rows = session.execute(
        select(StatementLine.as_of)
        .where(
            StatementLine.entity_id.in_(companies),
            StatementLine.figures == "ours",
            StatementLine.statement == "profit_loss",
        )
        .group_by(StatementLine.as_of)
        .having(func.count(func.distinct(StatementLine.entity_id)) == len(companies))
    )
    return set(rows.scalars())


def books_start(session: Session, companies: list[int]) -> date | None:
    return session.scalar(select(func.min(A.Entity.books_from)).where(A.Entity.id.in_(companies)))


def windows(period: Period, stored: set[date], books_from: date | None) -> Windows:
    """The statement pairs the period's figures come from, or why there are none."""
    if period.months:
        return _month_windows(period.months, stored, books_from)
    before = period.start - timedelta(days=1)
    within = [d for d in stored if period.start <= d <= period.end]
    if not within:
        return Windows(
            reason=f"no statement is stored between {period.start:%d-%b-%Y} and "
            f"{period.end:%d-%b-%Y}; run the statements command or choose whole months"
        )
    end = max(within)
    if _before_books(period.start, books_from):
        return Windows([(None, end)], cut=end != period.end)
    if before not in stored:
        return Windows(reason=f"no statement is stored for {before:%d-%b-%Y}; choose whole months")
    return Windows([(before, end)], cut=end != period.end)


def _month_windows(months: tuple[date, ...], stored: set[date], books_from: date | None) -> Windows:
    found = Windows()
    for month in months:
        end = _month_end(month, stored)
        if end is None:
            return Windows(reason=f"no statement is stored for the end of {month:%b-%Y}")
        if _before_books(month, books_from):
            before = None
        else:
            before = _month_end(month - timedelta(days=1), stored)
            if before is None:
                previous = month - timedelta(days=1)
                return Windows(reason=f"no statement is stored for the end of {previous:%b-%Y}")
        found.pairs.append((before, end))
        found.shifted = found.shifted or end != last_day(month)
    return found


def _month_end(month: date, stored: set[date]) -> date | None:
    """The month's statement date: its last day, else the first stored date within the
    slack after it."""
    end = last_day(month)
    candidates = sorted(d for d in stored if end <= d <= end + MONTH_END_SLACK)
    return candidates[0] if candidates else None


def _before_books(start: date, books_from: date | None) -> bool:
    return books_from is not None and start <= books_from
