"""A statement as a report page (D1 c1; docs/design/dashboard.md Section 0.1, screen 6): our
stored statement lines in the source's own layout and order, with a column per company, month
or quarter, a total, last year and the change, and whether the source's own statements match
for the companies and dates used.

Source-independent: lines come from `statement_lines` (ours, validated against the source's,
ADR-040), matched across companies by their line key (`match_key`), kept in the source's
order. A period's figure is the statement at its end less the one before its start
(core/report_periods.py). Several companies are added together: combined, without
inter-company eliminations.

Signs as people read a Profit & Loss: income and the profit lines positive when earned,
expenses positive when spent; a loss or a negative line stays negative.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from core.models import accounting as A  # noqa: N812
from core.models.reporting import StatementLine
from core.report_periods import Period, Windows, books_start, stored_dates, windows
from core.statements import CLOSING_STOCK_LINE, GROSS_PROFIT, NET_PROFIT, match_key

ZERO = Decimal(0)
VIEWS = ("company", "month", "quarter")  # what the columns are (besides the total)
SALES = "sales_accounts"


@dataclass(frozen=True)
class Column:
    key: str  # "company:3", "month:2026-04", "quarter:2026-Q1", "total", "last_year"
    label: str
    kind: str  # company, month, quarter, total, last_year


@dataclass
class Line:
    key: str  # the line's match key (the same line in every company)
    label: str
    level: str  # main, sub, detail (our totals: gross and net profit)
    section: str | None
    earned: bool = False  # income, a profit, or closing stock: more is better for the business
    values: dict[str, Decimal | None] = field(default_factory=dict)  # column key -> amount


@dataclass
class Matching:
    """Whether the source's own statements match ours for the companies and dates used."""

    dates: list[date]
    differing: int  # compared lines and totals that differ (company x date x line)
    compared: int
    unchecked: int  # company x date pairs without the source's own statement to compare

    @property
    def matches(self) -> bool:
        """Every company and date used was compared, and nothing differs."""
        return self.compared > 0 and self.differing == 0 and self.unchecked == 0


@dataclass
class Report:
    columns: list[Column]
    lines: list[Line]
    reason: str | None  # why there are no figures
    shifted: bool  # a month ran to a later stored date (Educational mode)
    last_year_reason: str | None
    matching: Matching
    net_sales: dict[str, Decimal]  # column key -> net sales (for % of sales)


def profit_loss(
    session: Session, companies: list[int], period: Period, view: str, compare: bool
) -> Report:
    stored = stored_dates(session, companies)
    books_from = books_start(session, companies)
    total = windows(period, stored, books_from)
    columns, column_windows = _columns(session, companies, period, view, stored, books_from)
    columns.append(Column("total", "Total", "total"))
    column_windows["total"] = (companies, total)
    last_year_reason = None
    if compare:
        last = windows(period.last_year(), stored, books_from)
        last_year_reason = last.reason
        columns.append(Column("last_year", "Last year", "last_year"))
        column_windows["last_year"] = (companies, last)
    if not total.available:
        return Report(columns, [], total.reason, False, last_year_reason, Matching([], 0, 0, 0), {})

    roles = _roles(session, companies)
    lines: dict[str, Line] = {}
    order: dict[str, tuple] = {}
    for column, (who, found) in column_windows.items():
        if not found.available:
            continue
        for key, value in _values(session, who, found, lines, order).items():
            lines[key].values[column] = value
    ordered = sorted(lines.values(), key=lambda line: order[line.key])
    for line in ordered:
        for column in column_windows:
            if column_windows[column][1].available:
                line.values.setdefault(column, ZERO)
            else:
                line.values[column] = None
    net_sales = {
        column: sum(
            (line.values.get(column) or ZERO for line in ordered if roles.get(line.key) == SALES),
            ZERO,
        )
        for column in column_windows
    }
    used = sorted(
        {d for _, found in column_windows.values() for pair in found.pairs for d in pair if d}
    )
    return Report(
        columns, ordered, None, total.shifted, last_year_reason,
        matching(session, companies, used), net_sales,
    )  # fmt: skip


def percent(value: Decimal | None, base: Decimal | None) -> Decimal | None:
    """`value` as a percentage of `base`, one decimal; None without a base."""
    if value is None or not base:
        return None
    return (value / base * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)


# --- columns -------------------------------------------------------------------------------


def _columns(
    session: Session,
    companies: list[int],
    period: Period,
    view: str,
    stored: set[date],
    books_from: date | None,
) -> tuple[list[Column], dict[str, tuple[list[int], Windows]]]:
    """The columns before the total, and the companies and statement windows of each."""
    columns: list[Column] = []
    found: dict[str, tuple[list[int], Windows]] = {}
    if view == "company":
        names = dict(
            session.execute(
                select(A.Entity.id, A.Entity.name).where(A.Entity.id.in_(companies))
            ).all()
        )
        for entity in companies:
            own = windows(period, stored_dates(session, [entity]), books_start(session, [entity]))
            key = f"company:{entity}"
            columns.append(Column(key, names.get(entity, f"Company {entity}"), "company"))
            found[key] = ([entity], own)
    elif view == "month":
        for month in period.month_starts():
            key = f"month:{month:%Y-%m}"
            columns.append(Column(key, f"{month:%b-%Y}", "month"))
            found[key] = (companies, windows(_clipped(period, [month]), stored, books_from))
    elif view == "quarter":
        start_month = (
            session.scalar(
                select(func.min(A.Entity.fy_start_month)).where(A.Entity.id.in_(companies))
            )
            or 4
        )
        by_quarter: dict[tuple[int, int], list[date]] = defaultdict(list)
        for month in period.month_starts():
            fy = month.year - (month.month < start_month)
            quarter = (month.month - start_month) % 12 // 3 + 1
            by_quarter[(fy, quarter)].append(month)
        for (fy, quarter), months in sorted(by_quarter.items()):
            key = f"quarter:{fy}-Q{quarter}"
            label = f"Q{quarter} FY {fy}-{(fy + 1) % 100:02d}"
            columns.append(Column(key, label, "quarter"))
            found[key] = (companies, windows(_clipped(period, months), stored, books_from))
    return columns, found


def _clipped(period: Period, months: list[date]) -> Period:
    """The part of the period in these months: whole months, or the range's part of them."""
    if period.months:
        return Period.of_months(months)
    whole = Period.of_months(months)
    return Period(max(period.start, whole.start), min(period.end, whole.end))


# --- lines ---------------------------------------------------------------------------------


def _roles(session: Session, companies: list[int]) -> dict[str, str | None]:
    """Line key -> the predefined role of the primary group the line is (None for the
    source's own lines and ours)."""
    rows = session.execute(
        select(A.AccountGroup.name, A.AccountGroup.predefined_role).where(
            A.AccountGroup.entity_id.in_(companies), A.AccountGroup.is_primary.is_(True)
        )
    )
    return {match_key(name): role for name, role in rows}


def _natures(session: Session, companies: list[int]) -> dict[str, str | None]:
    rows = session.execute(
        select(A.AccountGroup.name, A.AccountGroup.nature).where(
            A.AccountGroup.entity_id.in_(companies), A.AccountGroup.is_primary.is_(True)
        )
    )
    return {match_key(name): nature for name, nature in rows}


def _values(
    session: Session,
    companies: list[int],
    found: Windows,
    lines: dict[str, Line],
    order: dict[str, tuple],
) -> dict[str, Decimal]:
    """Each line's figure over the windows, as people read it; adds new lines to `lines`."""
    natures = _natures(session, companies)
    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for before, end in found.pairs:
        for sign, on in ((1, end), (-1, before)):
            if on is None:
                continue
            for line_no, label, level, section, amount in _lines_at(session, companies, on):
                key = match_key(label)
                reads_as_earned = (
                    label in (GROSS_PROFIT, NET_PROFIT) or natures.get(key) == "income"
                )
                if key not in lines:
                    better = reads_as_earned or label == CLOSING_STOCK_LINE
                    lines[key] = Line(key, label, level, section, earned=better)
                order[key] = min(order.get(key, (9_999,)), (line_no,))
                totals[key] += sign * (-amount if reads_as_earned else amount)
    return dict(totals)


def _lines_at(session: Session, companies: list[int], on: date) -> list[tuple]:
    return list(
        session.execute(
            select(
                StatementLine.line_no,
                StatementLine.label,
                StatementLine.level,
                StatementLine.section,
                StatementLine.amount,
            ).where(
                StatementLine.entity_id.in_(companies),
                StatementLine.as_of == on,
                StatementLine.statement == "profit_loss",
                StatementLine.figures == "ours",
            )
        )
    )


# --- matches the source --------------------------------------------------------------------


def matching(session: Session, companies: list[int], dates: list[date]) -> Matching:
    """How many of the compared lines and totals differ from the source's, at these dates
    (our stored comparison, `v_statement_check`: lines that aren't ours alone)."""
    if not dates:
        return Matching([], 0, 0, 0)
    ours = func.sum(case((StatementLine.figures == "ours", StatementLine.amount), else_=0))
    theirs = func.sum(case((StatementLine.figures == "source", StatementLine.amount), else_=0))
    grouped = (
        select((ours - theirs).label("difference"))
        .where(
            StatementLine.entity_id.in_(companies),
            StatementLine.as_of.in_(dates),
            StatementLine.statement == "profit_loss",
            StatementLine.level != "detail",
        )
        .group_by(StatementLine.entity_id, StatementLine.as_of, StatementLine.match_key)
        .having(func.count(func.distinct(StatementLine.figures)) == 2)
        .subquery()
    )
    compared, differing = session.execute(
        select(func.count(), func.coalesce(func.sum(grouped.c.difference != 0), 0))
    ).one()
    checked = session.execute(
        select(StatementLine.entity_id, StatementLine.as_of)
        .where(
            StatementLine.entity_id.in_(companies),
            StatementLine.as_of.in_(dates),
            StatementLine.statement == "profit_loss",
            StatementLine.figures == "source",
        )
        .distinct()
    ).all()
    unchecked = len(companies) * len(dates) - len(checked)
    return Matching(dates, int(differing or 0), int(compared or 0), unchecked)
