"""The Trial Balance page (ADR-055; P&L & KPIs › Trial Balance): every group, and on request
every ledger, with its debit or credit at a date and the totals, as the source's own Trial
Balance shows it for the financial year the date falls in. Formulas F-TB-001 to F-TB-005.

Why a financial year: the source opens its Trial Balance for the current financial year.
Our stored statements (core/statements.py) run from the books' beginning, so after a first
year end they differ from what a person sees in the source (the test company's recordings
of 2 May 2026: Sales 15,750 from the books' beginning, 12,000 for the year). For the year
that holds the date (core/dates.py `financial_year_ends`):

- **Assets, liabilities and capital:** the balance at the date, as in the Balance Sheet.
- **Income and expenses** (F-TB-003): only this financial year: the balance at the date less
  the balance at the last year end. Earlier years went into Profit & Loss A/c.
- **Stock** (F-TB-004): the opening stock of the year (the closing stock stored for the last
  year end), where the stock ledgers sit. Not the closing stock: a Trial Balance has the
  purchases and sales of the year, so it shows the stock the year started with.
- **Profit & Loss A/c** (F-TB-005): its own balance plus the profit of every earlier year
  (income less expenses up to the last year end, plus the opening stock of the books less
  the stock at the last year end).
- **The source's own lines:** Unadjusted Forex Gain/Loss taken from the source as the stored
  statements take it, and a group with foreign-currency ledgers that the stored statements
  take from the source (ADR-043) with the "Forex revaluation difference" row inside it.
- **Difference in opening balances:** when ours don't balance, the difference as a line in
  the column that balances them, inside the totals, as the source shows it.

Within the first financial year of the books both are the same, and equal the stored Trial
Balance line by line (test_trial_balance.py proves both against the recordings).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.account_tree import (
    ZERO,
    Row,
    Tree,
    add_ledgers,
    add_stock,
    group_names,
    settings_read,
    stored_figures,
    top_order,
)
from core.dates import financial_year_ends
from core.models import accounting as A  # noqa: N812
from core.models.reporting import StatementLine
from core.statements import (
    COMPUTED,
    NATURE_ORDER,
    OPENING_DIFFERENCE,
    PROFIT_LOSS_ACCOUNT,
    REVALUATION_DIFFERENCE,
    TAKEN,
    UNADJUSTED_FOREX,
    Figures,
    _books,
    match_key,
)

INCOME_EXPENSE = ("income", "expense")
YEAR_END_SLACK = timedelta(days=2)  # a year end's statement may be stored up to 2 days late


@dataclass
class TrialBalance:
    as_of: date | None
    year_start: date | None  # the financial year shown; None: from the books' beginning
    rows: list[Row] = field(default_factory=list)
    reason: str | None = None  # why there are no figures
    settings_missing: bool = False  # run the statements again (migration 0038)
    unproved: list[str] = field(default_factory=list)  # lines not yet proved against Tally

    @property
    def lines(self) -> list[Row]:
        """The rows at the top (primary groups and the source's own lines), without the
        difference in opening balances."""
        return [r for r in self.rows if r.depth == 0 and r.kind != "difference"]

    @property
    def debit(self) -> Decimal:
        """The lines' debit total (F-TB-002), as the source's Trial Balance exports it."""
        return sum((r.debit for r in self.lines), ZERO)

    @property
    def credit(self) -> Decimal:
        return sum((r.credit for r in self.lines), ZERO)

    @property
    def difference(self) -> Row | None:
        return next((r for r in self.rows if r.kind == "difference"), None)


@dataclass
class _Year:
    """The financial year the date falls in, and what it needs from the last year end."""

    start: date | None  # None: the year began on or before the books' beginning
    prior: dict[int, Decimal] = field(default_factory=dict)  # ledger id -> balance at the end
    stock: Decimal | None = None  # the stock stored for the last year end


def trial_balance(session: Session, companies: list[int], as_of: date) -> TrialBalance:
    """The Trial Balance of the companies at a stored statement date (several companies
    added up, without inter-company eliminations)."""
    tree = Tree()
    found = TrialBalance(as_of, None)
    order: list[str] = []
    lines: list[Row] = []
    for entity_id in companies:
        f = stored_figures(session, entity_id, as_of)
        if f is None:
            return TrialBalance(None, None, reason=f"no statement is stored for {as_of:%d-%b-%Y}")
        year = _year(session, entity_id, as_of)
        if year.start is not None and (year.stock is None and f.replaces_stock):
            return TrialBalance(
                None, None,
                reason=f"no stock value is stored for the year end before {year.start:%d-%b-%Y}; "
                "run the statements command",
            )  # fmt: skip
        found.year_start = year.start
        found.settings_missing |= not settings_read(session, entity_id)
        own = Tree()
        _company(session, own, f, entity_id, year, lines)
        tree.merge(own)
        order = order or top_order(f, tuple(NATURE_ORDER))
    rows = tree.ordered(order)
    merged = _merge_lines(lines)
    found.rows = rows + merged
    difference = found.debit - found.credit
    if difference:  # the lines don't balance: the difference, in the column that balances
        side = (ZERO, difference) if difference > 0 else (-difference, ZERO)
        found.rows.append(
            Row("x:difference", OPENING_DIFFERENCE, "difference", 0, None, fixed=side)
        )
        # Tally's exported Trial Balance has no such line (the test company's recording of
        # 1 April 2026, accounts not integrated: 63,500 Dr, 64,010 Cr): not yet proved.
        found.unproved.append(OPENING_DIFFERENCE)
    return found


def _company(
    session: Session, tree: Tree, f: Figures, entity_id: int, year: _Year, lines: list[Row]
) -> None:
    names = group_names(session, entity_id)
    natures = {g.id: g.nature for g in f.groups.values()}

    def value(ledger) -> Decimal:  # noqa: ANN001
        amount = f.value(ledger)
        if year.start is not None and natures.get(ledger.top) in INCOME_EXPENSE:
            amount -= year.prior.get(ledger.id, ZERO)  # this year only (F-TB-003)
        return amount

    add_ledgers(tree, f, entity_id, names, value)
    stock = _opening_stock(f, year)
    if stock is not None:
        add_stock(tree, f, entity_id, names, "Opening stock", stock)
    _taken_groups(session, tree, entity_id, f.source.as_of)
    lines.extend(_profit_carriers(f, entity_id, _earlier_profit(f, year, natures)))
    taken = f.source_line("trial_balance", UNADJUSTED_FOREX)
    if taken is not None:
        lines.append(
            Row("x:forex", UNADJUSTED_FOREX + TAKEN, "line", 0, None,
                fixed=(taken.debit or ZERO, taken.credit or ZERO))
        )  # fmt: skip


def _year(session: Session, entity_id: int, as_of: date) -> _Year:
    """The financial year of the date: from the books' beginning in the first year, else
    from the day after the last year end, with the ledgers' balances and the stock there."""
    entity = session.get(A.Entity, entity_id)
    if entity is None:
        return _Year(None)
    ends = financial_year_ends(entity.books_from, entity.fy_start_month, as_of)
    if not ends:
        return _Year(None)
    end = ends[-1]
    ledgers, _ = _books(session, entity_id, end)
    stock = session.scalar(
        select(A.StockValue.closing_value)
        .where(
            A.StockValue.entity_id == entity_id,
            A.StockValue.scope == "total",
            A.StockValue.as_of.between(end, end + YEAR_END_SLACK),
        )
        .order_by(A.StockValue.as_of)
        .limit(1)
    )
    return _Year(end + timedelta(days=1), {x.id: x.balance for x in ledgers}, stock)


def _opening_stock(f: Figures, year: _Year) -> Decimal | None:
    """The stock the Trial Balance shows (F-TB-004): the year's opening stock."""
    if not (f.replaces_stock and f.source.opening_stock is not None):
        return None
    return year.stock if year.start is not None else f.source.opening_stock


def _earlier_profit(f: Figures, year: _Year, natures: dict[int, str | None]) -> Decimal:
    """The result of every year before this one (canonical: a loss positive): income and
    expenses up to the last year end, and the stock from the books' opening to it."""
    if year.start is None:
        return ZERO
    result = sum(
        (year.prior.get(x.id, ZERO) for x in f.counted() if natures.get(x.top) in INCOME_EXPENSE),
        ZERO,
    )
    if f.replaces_stock and f.source.opening_stock is not None and year.stock is not None:
        result += f.source.opening_stock - year.stock
    return result


def _profit_carriers(f: Figures, entity_id: int, earlier: Decimal) -> list[Row]:
    """Profit & Loss A/c (F-TB-005) and any other ledger directly under Primary: its own
    balance, Profit & Loss A/c with the profit of earlier years."""
    carriers = [x for x in f.ledgers if x.key in f.source.profit_carriers]
    main = next(
        (x for x in carriers if match_key(x.name) == match_key(PROFIT_LOSS_ACCOUNT)),
        carriers[0] if carriers else None,
    )
    rows = []
    for ledger in carriers:
        amount = ledger.balance + (earlier if ledger is main else ZERO)
        if amount:
            rows.append(_line(f"x:carrier:{match_key(ledger.name)}", ledger.name, amount,
                              ledger.id, entity_id))  # fmt: skip
    if main is None and earlier:
        rows.append(_line("x:carrier:" + match_key(PROFIT_LOSS_ACCOUNT), PROFIT_LOSS_ACCOUNT,
                          earlier, None, entity_id))  # fmt: skip
    return rows


def _line(key: str, label: str, amount: Decimal, ledger_id: int | None, company: int) -> Row:
    row = Row(key, label, "line", 0, None, ledger_id=ledger_id, company=company)
    row.units[(company, "line", key)] = amount
    return row


def _merge_lines(lines: list[Row]) -> list[Row]:
    """The source's own lines of several companies, one row per label."""
    merged: dict[str, Row] = {}
    for row in lines:
        existing = merged.get(row.key)
        if existing is None:
            merged[row.key] = row
            continue
        if row.fixed is not None:
            a, b = existing.fixed or (ZERO, ZERO)
            existing.fixed = (a + row.fixed[0], b + row.fixed[1])
        else:
            for unit, amount in row.units.items():
                existing.units[unit] += amount
        existing.ledger_id = existing.company = None  # several companies: no one ledger
    return list(merged.values())


def _taken_groups(session: Session, tree: Tree, entity_id: int, as_of: date) -> None:
    """A group with foreign-currency ledgers that the stored Trial Balance takes from the
    source at this date (ADR-043): the gap the stored statements found between the source's
    line and ours ("Forex revaluation difference (per Tally, under review)") is a row inside
    it, and the group's line adds it. The gap comes from revaluing the ledgers, so it is the
    same for the financial year as from the books' beginning; the source's own line is from
    the books' beginning, so it is not used here (its stock would differ after a year end)."""
    stored = {
        label: (debit or ZERO, credit or ZERO)
        for label, debit, credit in session.execute(
            select(StatementLine.label, StatementLine.debit, StatementLine.credit).where(
                StatementLine.entity_id == entity_id,
                StatementLine.as_of == as_of,
                StatementLine.statement == "trial_balance",
                StatementLine.figures == "ours",
            )
        )
    }
    for label, (debit, credit) in stored.items():
        if not label.endswith(TAKEN):
            continue
        name = label.removesuffix(TAKEN)
        computed = stored.get(name + COMPUTED)
        row = tree.rows.get(f"g:/{match_key(name)}")
        if computed is None or row is None:
            continue
        gap = (debit - computed[0], credit - computed[1])
        tree.rows[f"{row.key}/x:revaluation"] = Row(
            f"{row.key}/x:revaluation", REVALUATION_DIFFERENCE, "line", row.depth + 1, row.key,
            (3, 0, ""), fixed=gap,
        )  # fmt: skip
        row.label = name + TAKEN
        row.fixed = (row.debit + gap[0], row.credit + gap[1])
