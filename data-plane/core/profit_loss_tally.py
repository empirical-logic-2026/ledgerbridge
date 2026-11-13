"""The Profit & Loss in Tally's horizontal layout (ADR-056; the P&L page's default view):
TallyPrime's Profit & Loss A/c with its two sides. Formulas F-PL-011 to F-PL-017.

The placement rules come from Tally's own recorded report (its HTML export keeps the two
sides; tests/fixtures/tally/rules/pl_sides, recorded 2026-11-13 with inventory integration
on and off), approved by the developer:

1. A group goes on the side of its balance for the period: a debit on the left, a credit on
   the right, shown positive (F-PL-011). So a direct expense in credit is on the right, and
   sales in debit are on the left.
2. A group with no balance is still listed, with no amount, on its usual side (expenses on
   the left, incomes on the right).
3. The gross block (the groups that affect gross profit) comes first: Opening Stock first on
   the left, Closing Stock last on the right (F-PL-017).
4. Within a side, the groups follow the source's order (its sort position).
5. A gross profit is "Gross Profit c/o" at the end of the left gross block and "Gross Profit
   b/f" first on the right of the net block; a gross loss is "Gross Loss c/o" at the end of
   the right gross block and "Gross Loss b/f" first on the left (F-PL-012). The gross block
   ends with one subtotal, equal on both sides (F-PL-013).
6. The net block: the other groups by rule 1; a "Nett Profit" last on the left, a "Nett Loss"
   last on the right (F-PL-014); one Total per side, equal (F-PL-015).

**Figures** are the stored statements' (core/statements.py `Figures`, as stored by the
statements refresh): each group's total at the period's end less at the day before its
start (F-PL-007); the opening stock is the stock at that day (the books' opening stock when
the period starts with the books), the closing stock the stock at the end (Tally's own
values). So the period must end on a stored statement date: else `reason` says why and
`nearest` offers the stored dates around it.

**Several companies** (F-PL-015): each company's amounts in a column of its own, and the total. A
row's side follows the total; a company whose own balance is on the other side shows a
negative amount there. Combined, without inter-company eliminations.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from core.account_tree import ZERO, Tree, add_ledgers, group_names, stored_figures
from core.account_tree import Row as TreeRow
from core.report_periods import Period, books_start, stored_dates, windows
from core.statements import Figures, match_key

PL_NATURES = ("income", "expense")
TOTAL = "total"


@dataclass
class Row:
    key: str  # "g:/<group>" (opens its drill-down), "x:opening_stock", "x:gross_co", ...
    label: str
    kind: str  # group, stock, gross_carried, gross_brought, net_result
    values: dict[str, Decimal | None] = field(default_factory=dict)  # column -> amount
    group: str | None = None  # the group's match key, for the drill-down


@dataclass
class Side:
    rows: list[Row] = field(default_factory=list)
    total: dict[str, Decimal] = field(default_factory=dict)  # the block's subtotal or Total


@dataclass
class Block:
    left: Side = field(default_factory=Side)
    right: Side = field(default_factory=Side)


@dataclass
class TallyProfitLoss:
    columns: list[str]  # "company:3", ..., "total"
    start: date | None  # the period shown
    end: date | None
    gross: Block = field(default_factory=Block)
    net: Block = field(default_factory=Block)
    gross_profit: dict[str, Decimal] = field(default_factory=dict)  # a loss negative
    net_profit: dict[str, Decimal] = field(default_factory=dict)
    reason: str | None = None
    nearest: list[date] = field(default_factory=list)  # stored dates around the end


@dataclass
class _Group:
    key: str
    name: str
    order: tuple[int, int, str]
    nature: str | None
    gross: bool
    amounts: dict[str, Decimal] = field(default_factory=dict)  # canonical (debit positive)


def statement_span(
    session: Session, companies: list[int], period: Period
) -> tuple[date | None, date | None, str | None, list[date]]:
    """(the day before the start or None at the books' beginning, the end, why there is
    none, the stored dates around the end): the statements a period's figures come from."""
    stored = stored_dates(session, companies)
    found = windows(period, stored, books_start(session, companies))
    if found.reason is not None or not found.pairs:
        return None, None, found.reason or "no statement is stored", _nearest(stored, period.end)
    if found.cut:  # a range ending between stored dates: Tally's stock isn't known there
        return None, None, (
            f"no statement is stored for {period.end:%d-%b-%Y}: Tally's closing stock, and so "
            "the profit, is known only at a stored statement date"
        ), _nearest(stored, period.end)  # fmt: skip
    if period.months and not _adjacent(period.months):
        return None, None, "Tally's layout needs months next to each other", []
    return found.pairs[0][0], found.pairs[-1][1], None, []


def _adjacent(months: tuple[date, ...]) -> bool:
    return all(
        (b.year * 12 + b.month) - (a.year * 12 + a.month) == 1
        for a, b in zip(months, months[1:], strict=False)
    )


def _nearest(stored: set[date], on: date) -> list[date]:
    """The stored dates just before and just after a date (those that exist)."""
    before = max((d for d in stored if d <= on), default=None)
    after = min((d for d in stored if d > on), default=None)
    return [d for d in (before, after) if d is not None]


def tally_profit_loss(session: Session, companies: list[int], period: Period) -> TallyProfitLoss:
    columns = [f"company:{c}" for c in companies] + [TOTAL]
    before, end, reason, nearest = statement_span(session, companies, period)
    if end is None:
        return TallyProfitLoss(columns, None, None, reason=reason, nearest=nearest)
    groups: dict[str, _Group] = {}
    stock: dict[str, dict[str, Decimal]] = {"opening": {}, "closing": {}}
    for entity in companies:
        column = f"company:{entity}"
        f_end = stored_figures(session, entity, end)
        f_before = stored_figures(session, entity, before) if before else None
        if f_end is None or (before is not None and f_before is None):
            missing = end if f_end is None else before
            reason = f"no statement is stored for {missing:%d-%b-%Y}"
            return TallyProfitLoss(columns, None, None, reason=reason)
        _add_groups(groups, column, f_end, f_before)
        if _has_stock(f_end):
            opening = f_before.source.closing_stock if f_before else f_end.source.opening_stock
            stock["opening"][column] = opening or ZERO
            stock["closing"][column] = f_end.source.closing_stock or ZERO
    for name in groups.values():
        name.amounts[TOTAL] = sum(name.amounts.values(), ZERO)
    for kind in stock:
        if stock[kind]:
            stock[kind][TOTAL] = sum(stock[kind].values(), ZERO)
    found = TallyProfitLoss(columns, before + timedelta(days=1) if before else None, end)
    _lay_out(found, sorted(groups.values(), key=lambda g: g.order), stock)
    return found


def _has_stock(f: Figures) -> bool:
    return f.source.opening_stock is not None or f.source.closing_stock is not None


def _add_groups(
    groups: dict[str, _Group], column: str, f_end: Figures, f_before: Figures | None
) -> None:
    """Each income and expense group's movement in the period (F-PL-007), by its name."""
    end_totals = f_end.totals()
    before_totals = f_before.totals() if f_before else {}
    before_ids = {match_key(g.name): g.id for g in (f_before.groups.values() if f_before else [])}
    for n, group in enumerate(f_end.ordered_groups(PL_NATURES)):
        key = match_key(group.name)
        moved = end_totals.get(group.id, ZERO) - before_totals.get(before_ids.get(key, -1), ZERO)
        found = groups.setdefault(
            key,
            _Group(key, group.name, (group.sort_position or 10**9, n, key), group.nature,
                   group.affects_gross_profit),
        )  # fmt: skip
        found.amounts[column] = found.amounts.get(column, ZERO) + moved


def _side_of(group: _Group) -> str:
    """Rule 1 and 2: the side of the total's balance; with none, the nature's side."""
    total = group.amounts[TOTAL]
    if total > 0:
        return "left"
    if total < 0:
        return "right"
    return "left" if group.nature == "expense" else "right"


def _shown(amounts: dict[str, Decimal], side: str) -> dict[str, Decimal | None]:
    """Amounts as a side shows them: a debit on the left, a credit on the right, positive."""
    sign = 1 if side == "left" else -1
    return {c: v * sign if v else None for c, v in amounts.items()}  # nothing: blank, as Tally


def _lay_out(found: TallyProfitLoss, groups: list[_Group], stock: dict) -> None:
    columns = found.columns
    gross, net = found.gross, found.net
    if stock["opening"]:
        gross.left.rows.append(Row("x:opening_stock", "Opening Stock", "stock",
                                   dict(stock["opening"])))  # fmt: skip
    for group in groups:
        block = gross if group.gross else net
        side = _side_of(group)
        row = Row(f"g:/{group.key}", group.name, "group", _shown(group.amounts, side), group.key)
        getattr(block, side).rows.append(row)
    if stock["closing"]:
        gross.right.rows.append(Row("x:closing_stock", "Closing Stock", "stock",
                                    dict(stock["closing"])))  # fmt: skip
    gross_profit = {c: _sum(gross.right, c) - _sum(gross.left, c) for c in columns}
    found.gross_profit = gross_profit
    profit = gross_profit[TOTAL] >= 0
    word = "Profit" if profit else "Loss"
    carried = Row("x:gross_co", f"Gross {word} c/o", "gross_carried",
                  {c: v if profit else -v for c, v in gross_profit.items()})  # fmt: skip
    (gross.left if profit else gross.right).rows.append(carried)
    for side in (gross.left, gross.right):
        side.total = {c: _sum(side, c) for c in columns}
    brought = Row("x:gross_bf", f"Gross {word} b/f", "gross_brought", dict(carried.values))
    (net.right if profit else net.left).rows.insert(0, brought)
    net_profit = {c: _sum(net.right, c) - _sum(net.left, c) for c in columns}
    found.net_profit = net_profit
    made = net_profit[TOTAL] >= 0
    result = Row("x:net", "Nett Profit" if made else "Nett Loss", "net_result",
                 {c: v if made else -v for c, v in net_profit.items()})  # fmt: skip
    (net.left if made else net.right).rows.append(result)
    for side in (net.left, net.right):
        side.total = {c: _sum(side, c) for c in columns}


def _sum(side: Side, column: str) -> Decimal:
    return sum((row.values.get(column) or ZERO for row in side.rows), ZERO)


# --- the drill-down of a line ---------------------------------------------------------------


@dataclass
class DrillRow:
    key: str
    label: str
    kind: str  # group, ledger
    depth: int  # 0: the line itself
    parent: str | None
    amount: Decimal  # as the line's side shows it (F-PL-016)
    ledger_id: int | None = None
    company: int | None = None


def drill(
    session: Session, companies: list[int], period: Period, group: str, side: str
) -> tuple[list[DrillRow], str | None]:
    """A group line's sub-groups and ledgers with their movement in the period, as its side
    shows them (a debit positive on the left, a credit on the right); each level adds up to
    the line. (rows, why there are none)."""
    before, end, reason, _ = statement_span(session, companies, period)
    if end is None:
        return [], reason
    tree = Tree()
    for entity in companies:
        f_end = stored_figures(session, entity, end)
        if f_end is None:
            return [], f"no statement is stored for {end:%d-%b-%Y}"
        f_before = stored_figures(session, entity, before) if before else None
        earlier = {x.id: f_before.value(x) for x in f_before.ledgers} if f_before else {}
        tops = {g.id for g in f_end.groups.values() if match_key(g.name) == group}
        own = Tree()
        add_ledgers(
            own, f_end, entity, group_names(session, entity),
            lambda x, f=f_end, e=earlier: f.value(x) - e.get(x.id, ZERO),
            lambda x, t=tops: x.top in t,
        )  # fmt: skip
        tree.merge(own)
    root = tree.rows.get(f"g:/{group}")
    if root is None:
        return [], "this line has no ledgers to show"
    sign = 1 if side == "left" else -1
    rows = [r for r in tree.ordered([root.key]) if r.key == root.key or _below(r, root.key, tree)]
    return [
        DrillRow(r.key, r.label, r.kind, r.depth, r.parent, r.amount * sign, r.ledger_id, r.company)
        for r in rows
    ], None


def _below(row: TreeRow, root: str, tree: Tree) -> bool:
    current: TreeRow | None = row
    while current is not None and current.parent is not None:
        if current.parent == root:
            return True
        current = tree.rows.get(current.parent)
    return False
