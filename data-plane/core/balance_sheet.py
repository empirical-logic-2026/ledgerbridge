"""The Balance Sheet module (RPT-003, RPT-014; docs/design/dashboard.md Section 0.4): our stored
Balance Sheet (validated against the source's, ADR-040) at the period's end and at the end of
the period it is compared with, line by line with the change, and the ratios. Source-
independent: groups by their predefined role, never by name. Formulas F-BS-005, F-BS-006,
F-RAT-004 to F-RAT-010 in docs/formula-sheet.md.

A Balance Sheet is the position **at** a date: the period's end, or the last stored date
within the period (core/report_periods.py `windows`). Assets are shown as debits, liabilities
and capital as credits, both positive.

- **Current ratio** = current assets ÷ current liabilities; **quick ratio** = (current assets −
  closing stock) ÷ current liabilities; **debt to equity** = borrowings ÷ (Capital Account +
  Profit & Loss A/c). Current assets, current liabilities and borrowings in the form of
  Schedule III, ledger by ledger (core/ratios.py); equity from the main lines at the date.
- **Receivable days** = receivables ÷ net sales × days; **payable days** = payables ÷ net
  purchases × days; **inventory days** = closing stock ÷ cost of sales × days, over the days
  from the period's start to the date; **working-capital days** = receivable + inventory −
  payable days.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.home import (
    CAPITAL,
    PAYABLES,
    RECEIVABLES,
    balance,
    profit_loss_figures,
    stock_value,
)
from core.models import accounting as A  # noqa: N812
from core.models.reporting import StatementLine
from core.ratios import Position, position
from core.report_periods import Period, books_start, stored_dates, windows
from core.sales import PURCHASES_SIDE, SALES_SIDE, Facets, period_totals
from core.statements import PROFIT_LOSS_ACCOUNT, match_key

ZERO = Decimal(0)
# The ratios built from current assets, current liabilities and borrowings (core/ratios.py).
POSITION_RATIOS = ("current_ratio", "quick_ratio", "debt_to_equity")


@dataclass
class SheetLine:
    key: str
    label: str
    level: str  # main, sub, detail
    section: str  # assets, liabilities
    order: int
    values: dict[str, Decimal | None] = field(default_factory=dict)  # "now", "before"


@dataclass
class RatioFigure:
    key: str
    label: str
    unit: str  # times, days
    values: dict[str, Decimal | None] = field(default_factory=dict)  # "now", "before"
    # Current assets, liabilities and borrowings behind it ("now", "before"; core/ratios.py).
    positions: dict[str, Position] = field(default_factory=dict)


@dataclass
class Sheet:
    as_of: date | None  # the date the figures are at
    before_as_of: date | None
    reason: str | None  # why there are no figures
    before_reason: str | None
    lines: list[SheetLine]
    totals: dict[str, dict[str, Decimal | None]]  # assets / liabilities -> now / before
    ratios: list[RatioFigure]


@dataclass
class _At:
    """One side of the comparison: the date and the figures there."""

    period: Period
    on: date | None
    reason: str | None


def balance_sheet(
    session: Session, companies: list[int], period: Period, before: Period | None
) -> Sheet:
    stored = stored_dates(session, companies)
    books_from = books_start(session, companies)
    sides = {"now": _at(period, stored, books_from)}
    if before is not None:
        sides["before"] = _at(before, stored, books_from)
    roles = _roles(session, companies)
    lines: dict[tuple[str, str], SheetLine] = {}
    totals: dict[str, dict[str, Decimal | None]] = {"assets": {}, "liabilities": {}}
    ratios: dict[str, RatioFigure] = {}
    for name, side in sides.items():
        if side.on is None:
            continue
        found = _lines_at(session, companies, side.on)
        for line_no, label, level, section, amount in found:
            key = (section, match_key(label))
            line = lines.setdefault(
                key, SheetLine(f"{section}:{key[1]}", label, level, section, line_no)
            )
            line.order = min(line.order, line_no)
            shown = amount if section == "assets" else -amount
            line.values[name] = (line.values.get(name) or ZERO) + shown
        for section in totals:
            totals[section][name] = sum(
                (
                    (amount if section == "assets" else -amount)
                    for _, _, level, s, amount in found
                    if s == section and level == "main"
                ),
                ZERO,
            )
        for ratio in _ratios(session, companies, side, found, roles, stored, books_from):
            ratios.setdefault(ratio.key, RatioFigure(ratio.key, ratio.label, ratio.unit))
            ratios[ratio.key].values[name] = ratio.values["now"]
            if "now" in ratio.positions:
                ratios[ratio.key].positions[name] = ratio.positions["now"]
    now = sides["now"]
    compared = sides.get("before")
    return Sheet(
        as_of=now.on,
        before_as_of=compared.on if compared else None,
        reason=now.reason,
        before_reason=compared.reason if compared else None,
        lines=sorted(lines.values(), key=lambda line: (line.section != "assets", line.order)),
        totals=totals,
        ratios=list(ratios.values()),
    )


def _at(period: Period, stored: set[date], books_from: date | None) -> _At:
    found = windows(period, stored, books_from)
    return _At(period, found.end, found.reason)


def _roles(session: Session, companies: list[int]) -> dict[str, str | None]:
    """Line key -> the predefined role of the primary group the line is."""
    rows = session.execute(
        select(A.AccountGroup.name, A.AccountGroup.predefined_role).where(
            A.AccountGroup.entity_id.in_(companies), A.AccountGroup.is_primary.is_(True)
        )
    )
    return {match_key(name): role for name, role in rows}


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
                StatementLine.statement == "balance_sheet",
                StatementLine.figures == "ours",
            )
        )
    )


def ratio_of(part: Decimal | None, whole: Decimal | None, places: str = "0.01") -> Decimal | None:
    """part ÷ whole, rounded; None without a whole."""
    if part is None or whole is None or whole == 0:
        return None
    return (part / whole).quantize(Decimal(places), ROUND_HALF_UP)


def days_of(part: Decimal | None, whole: Decimal | None, days: int) -> Decimal | None:
    """part ÷ whole × days, whole days; None without a whole."""
    found = ratio_of(part, whole, "0.000001")
    return None if found is None else (found * days).quantize(Decimal("1"), ROUND_HALF_UP)


def position_ratios(parts: Position, equity: Decimal) -> dict[str, Decimal | None]:
    """Current ratio (F-RAT-008), quick ratio (F-RAT-009) and debt to equity (F-RAT-010)
    from current assets, current liabilities and borrowings, and the equity."""
    assets, liabilities = parts.current_assets, parts.current_liabilities
    return {
        "current_ratio": ratio_of(assets, liabilities),
        "quick_ratio": ratio_of(assets - parts.stock, liabilities),
        "debt_to_equity": ratio_of(parts.total_borrowings, equity),
    }


def _ratios(
    session: Session,
    companies: list[int],
    side: _At,
    found: list[tuple],
    roles: dict[str, str | None],
    stored: set[date],
    books_from: date | None,
) -> list[RatioFigure]:
    """The ratios at the side's date (F-RAT-004 to F-RAT-010)."""
    if side.on is None:
        return []
    on = side.on

    def main(role: str) -> Decimal:
        return sum(
            (
                amount if section == "assets" else -amount
                for _, label, level, section, amount in found
                if level == "main" and roles.get(match_key(label)) == role
            ),
            ZERO,
        )

    profit_loss_line = sum(
        (
            -amount
            for _, label, level, _, amount in found
            if level == "main" and label == PROFIT_LOSS_ACCOUNT
        ),
        ZERO,
    )
    parts = position(session, companies, on)
    equity = main(CAPITAL) + profit_loss_line
    parts.equity = equity
    from_parts = position_ratios(parts, equity)
    stock = stock_value(session, companies, on)
    span = Period(side.period.start, on)
    days = (on - side.period.start).days + 1
    sales = period_totals(session, companies, span, Facets(), SALES_SIDE).net
    purchases = period_totals(session, companies, span, Facets(), PURCHASES_SIDE).net
    cost = profit_loss_figures(session, companies, windows(span, stored, books_from))
    cost_of_sales = cost.values.get("cost_of_sales") if cost.reason is None else None
    receivable = days_of(balance(session, companies, (RECEIVABLES,), on), sales, days)
    payable = days_of(-balance(session, companies, (PAYABLES,), on), purchases, days)
    inventory = days_of(stock, cost_of_sales, days)
    working = (
        receivable + inventory - payable if None not in (receivable, inventory, payable) else None
    )
    figures = [
        ("current_ratio", "Current ratio", "times", from_parts["current_ratio"]),
        ("quick_ratio", "Quick ratio", "times", from_parts["quick_ratio"]),
        ("debt_to_equity", "Debt to equity", "times", from_parts["debt_to_equity"]),
        ("receivable_days", "Receivable days", "days", receivable),
        ("payable_days", "Payable days", "days", payable),
        ("inventory_days", "Inventory days", "days", inventory),
        ("working_capital_days", "Working-capital days", "days", working),
    ]  # fmt: skip
    behind = {"now": parts}
    return [
        RatioFigure(key, label, unit, {"now": value}, behind if key in POSITION_RATIOS else {})
        for key, label, unit, value in figures
    ]
