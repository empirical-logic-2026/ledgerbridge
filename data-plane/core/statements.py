"""The Trial Balance, Profit & Loss and Balance Sheet as the source lays them out, built from
our books, and checked against the source's own line by line (ADR-040; RPT-012, VAL-015).
Source-independent: the source's figures arrive as `connectors.base.SourceStatements`.

Where it fits: validation (core/validation.py) and the statements command
(workers/statements.py) read the source's statements for a date through the connector, then
call `refresh`: it stores the source's figures (stock values, foreign-currency revaluations,
its statement lines), builds ours, stores them in `ledgerbridge_reporting.statement_lines`
(the views read them) and returns the differences.

Ours follow the source's own figures where the books alone can't give them (ADR-033,
ADR-040, decision 2026-10-22):
- **Stock:** the opening and closing stock the source's Profit and Loss uses, in place of
  the stock ledgers (`ledger_kind` stock): at the opening value in the Trial Balance and at
  the closing value in the Balance Sheet, under the stock ledgers' primary group. Integrated
  with inventory that stock is the items' value; not integrated it is the stock ledgers'
  own, which in Tally can be closing values entered by date rather than their balance
  (pilot 2026-10-24: a Balance Sheet differing by the stock at the last year end less the
  opening stock).
- **Foreign-currency ledgers:** at the balance the source reports (revalued at current
  rates). The "Unadjusted Forex Gain/Loss" line is **taken from the source** (labelled so):
  the rule behind it isn't fully known (pilot 2026-10-24: one company's line differed from
  the ledgers' book value less their revalued balance, mostly by its difference in opening
  balances but not always). Ours, computed that way (its debit the losses and its credit
  the gains, ledger by ledger, as recorded on the test company, 2026-10-23), stays beside
  it as a detail line, never compared.
- **A group holding foreign-currency ledgers, temporary stopgap (ADR-043):** at a date where
  the source shows its forex line and our group line differs from the source's by more than
  the validation tolerance (the comparison's: `connections.config.validation_tolerance`,
  default 0, exact), the line is the source's (labelled), ours is a "(computed)" detail line
  and a detail line "Forex revaluation difference (per Tally, under review)" makes up the
  gap, so the ledgers plus that line equal the group's total. At every other date ours is
  the line and is compared. Exit: replace it with the computed figure once the revaluation
  rule is found (pilot 2026-10-24: one company's Current Assets at 18 of 78 dates).
- **The Balance Sheet's stock:** the Profit and Loss's closing stock, computed and compared
  at every date. (Taken from the source after a first year end from 2026-10-24 to its
  retirement: the pilot then matched at every date with ours, ADR-043's exit condition.)
- **Ledgers directly under Primary** (the source's profit carriers, e.g. Tally's Profit &
  Loss A/c) belong to the Profit & Loss A/c line: their balance (Opening Balance) plus the
  period's profit (Current Period); on the liabilities side for a profit, the assets side
  for a loss.

Lines are one per primary group (the group's current name), plus the source's own lines
(Cost of Sales with Opening Stock, purchases, Closing Stock and then the other expenses
that affect gross profit, e.g. Direct Expenses; Profit & Loss A/c; Unadjusted Forex
Gain/Loss). Direct Incomes stay a line of their own (recorded on the test company,
2026-10-23). Our extra lines (Gross Profit, Net Profit, the two parts of
Profit & Loss A/c, a difference in opening balances) are `detail`, never compared.
"""

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from connectors.base import SourceStatements, StatementLine
from core.models import accounting as A  # noqa: N812
from core.models.base import utcnow
from core.models.reporting import StatementLine as LineRow

ZERO = Decimal(0)
PURCHASES = "5110"  # the standard account of purchase groups: inside Cost of Sales
COST_OF_SALES = "Cost of Sales"  # the source's own block line
# Our own lines (detail, never compared); the dashboard reads them (core/overview.py).
GROSS_PROFIT, NET_PROFIT = "Gross Profit", "Net Profit"
CLOSING_STOCK_LINE = "Less: Closing Stock"  # inside Cost of Sales
NATURE_ORDER = {"equity": 0, "liability": 1, "asset": 2, "income": 3, "expense": 4}
PROFIT_LOSS_ACCOUNT = "Profit & Loss A/c"
UNADJUSTED_FOREX = "Unadjusted Forex Gain/Loss"
# A line ours take from the source's own report, because no rule for it is known: labelled
# so in the views and compared like any other (the suffix is ignored by match_key).
TAKEN = " (taken from the source)"
COMPUTED = " (computed)"  # ours beside a line taken from the source: a detail line
COMPUTED_FOREX = UNADJUSTED_FOREX + COMPUTED
REVALUATION_DIFFERENCE = "Forex revaluation difference (per Tally, under review)"
OPENING_DIFFERENCE = "Difference in opening balances"


def match_key(label: str) -> str:
    """A line's label as both sides are compared: without the source's "Add: " / "Less: "
    and trailing ":", spaces collapsed, case folded."""
    text = " ".join(label.split()).casefold()
    text = text.removesuffix(TAKEN.casefold()).removesuffix(COMPUTED.casefold())
    for prefix in ("add:", "less:"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    return text.rstrip(":").strip()


@dataclass
class _Ledger:
    id: int
    key: str
    name: str
    top: int  # the primary group it rolls up to
    kind: str
    opening: Decimal
    balance: Decimal
    groups: tuple[str, ...] = ()  # source keys of its group and those above, up to `top`

    @property
    def branch(self) -> str | None:
        """The sub-group directly under its primary group it sits in (None: in the primary)."""
        return self.groups[-2] if len(self.groups) > 1 else None


@dataclass
class _Group:
    id: int
    name: str
    nature: str | None
    affects_gross_profit: bool
    standard_code: str | None


@dataclass
class Difference:
    """One line (or total) where ours and the source's differ."""

    statement: str
    key: str
    label: str
    ours: Decimal
    source: Decimal
    part: str = "amount"  # amount; a trial balance line's debit or credit
    kind: str = "amount"  # amount, missing_ours, missing_source, total


@dataclass
class Comparison:
    as_of: date
    compared: int = 0
    differences: list[Difference] = field(default_factory=list)
    stock_before: tuple[Decimal | None, Decimal | None] | None = None  # stored before the read
    taken: list[Difference] = field(default_factory=list)  # taken lines unlike ours computed


# --- our books as of a date ---------------------------------------------------------------


def _books(
    session: Session, entity_id: int, as_of: date
) -> tuple[list[_Ledger], dict[int, _Group]]:
    """Every ledger's balance as of the date (opening + effective lines), with the primary
    group it rolls up to; and the primary groups."""
    groups = {
        gid: (parent, name, nature, gross, code, key)
        for gid, parent, name, nature, gross, code, key in session.execute(
            select(
                A.AccountGroup.id,
                A.AccountGroup.parent_id,
                A.AccountGroup.name,
                A.AccountGroup.nature,
                A.AccountGroup.affects_gross_profit,
                A.StandardAccount.code,
                A.AccountGroup.source_key,
            )
            .outerjoin(
                A.StandardAccount, A.StandardAccount.id == A.AccountGroup.standard_account_id
            )
            .where(A.AccountGroup.entity_id == entity_id, A.AccountGroup.is_deleted.is_(False))
        )
    }

    def top(gid: int) -> int:
        seen = set()
        while groups.get(gid, (None,))[0] is not None and gid not in seen:
            seen.add(gid)
            gid = groups[gid][0]
        return gid

    def path(gid: int) -> tuple[str, ...]:
        """Source keys of the group and every group above it, up to the primary group."""
        keys, seen = [], set()
        while gid in groups and gid not in seen:
            seen.add(gid)
            keys.append(groups[gid][5])
            gid = groups[gid][0]
        return tuple(keys)

    movements = (
        select(A.VoucherLine.ledger_id, func.sum(A.VoucherLine.amount).label("moved"))
        .where(
            A.VoucherLine.entity_id == entity_id,
            A.VoucherLine.is_effective.is_(True),
            A.VoucherLine.voucher_date <= as_of,
        )
        .group_by(A.VoucherLine.ledger_id)
        .subquery()
    )
    ledgers = [
        _Ledger(
            lid,
            key,
            name,
            top(gid),
            kind,
            Decimal(opening),
            Decimal(opening) + Decimal(moved),
            path(gid),
        )  # fmt: skip
        for lid, key, name, gid, kind, opening, moved in session.execute(
            select(
                A.Ledger.id,
                A.Ledger.source_key,
                A.Ledger.name,
                A.Ledger.group_id,
                A.Ledger.ledger_kind,
                A.Ledger.opening_balance,
                func.coalesce(movements.c.moved, 0),
            )
            .outerjoin(movements, movements.c.ledger_id == A.Ledger.id)
            .where(A.Ledger.entity_id == entity_id, A.Ledger.is_deleted.is_(False))
        )
    ]
    tops = {ledger.top for ledger in ledgers}
    primary = {
        gid: _Group(gid, name, nature, bool(gross), code)
        for gid, (_, name, nature, gross, code, _key) in groups.items()
        if gid in tops
    }
    return ledgers, primary


# --- building ours ------------------------------------------------------------------------


@dataclass
class Figures:
    """Our books and the source's figures for one date, sorted the way the statements need."""

    ledgers: list[_Ledger]
    groups: dict[int, _Group]
    source: SourceStatements
    tolerance: Decimal = ZERO  # "differs": by more than this, as the comparison

    @property
    def integrated(self) -> bool:
        return bool(self.source.integrated) and self.source.closing_stock is not None

    @property
    def replaces_stock(self) -> bool:
        """Whether the source's stock stands in for the stock ledgers: it reports its stock,
        and accounts are integrated with inventory or there are stock ledgers."""
        if self.source.closing_stock is None:
            return False
        return self.integrated or any(x.kind == "stock" for x in self.ledgers)

    def value(self, ledger: _Ledger) -> Decimal:
        """A ledger as the source's statements count it: foreign-currency ledgers at the
        balance the source reports."""
        return self.source.revalued.get(ledger.key, ledger.balance)

    def counted(self) -> list[_Ledger]:
        """Ledgers in the group lines: not the profit carriers, and not the stock ledgers
        when the stock value replaces them."""
        return [
            ledger
            for ledger in self.ledgers
            if ledger.key not in self.source.profit_carriers
            and not (self.replaces_stock and ledger.kind == "stock")
        ]

    def unit(self, ledger: _Ledger) -> tuple[str, object]:
        """What the source's Trial Balance splits a line into debit and credit by: the
        ledger itself, or the highest group above it whose balances the source nets for
        reporting (Tally's "Nett Debit/Credit Balances for Reporting", recorded on the test
        company, 2026-10-24)."""
        netted = [key for key in ledger.groups if key in self.source.netted_groups]
        return ("group", netted[-1]) if netted else ("ledger", ledger.id)

    def totals(self) -> dict[int, Decimal]:
        """Each primary group's total of the ledgers counted in its line."""
        totals: dict[int, Decimal] = defaultdict(lambda: ZERO)
        for ledger in self.counted():
            totals[ledger.top] += self.value(ledger)
        return totals

    def stock_group(self) -> int | None:
        """The primary group the stock ledgers roll up to (e.g. Current Assets); without
        stock ledgers, the current assets group (standard account 1270)."""
        found = next((x.top for x in self.ledgers if x.kind == "stock"), None)
        if found is None:
            found = next((g.id for g in self.groups.values() if g.standard_code == "1270"), None)
        return found

    def forex(self) -> list[Decimal]:
        """Each foreign-currency ledger's unadjusted gain or loss: its book value less the
        balance the source reports (a loss is a debit, a gain a credit)."""
        return [
            x.balance - self.source.revalued[x.key]
            for x in self.ledgers
            if x.key in self.source.revalued
        ]

    def foreign_group_from_source(self, statement: str, group: _Group) -> StatementLine | None:
        """The source's own line for a group holding foreign-currency ledgers, at a date the
        source shows its forex line (the ADR-043 stopgap's first two conditions); None
        otherwise. The caller takes it only where ours differs."""
        shows_forex = any(
            self.source_line(s, UNADJUSTED_FOREX) for s in ("trial_balance", "balance_sheet")
        )
        holds_foreign = any(
            x.top == group.id and x.key in self.source.revalued for x in self.ledgers
        )
        if not (shows_forex and holds_foreign):
            return None
        return self.source_line(statement, group.name)

    def source_line(self, statement: str, label: str) -> StatementLine | None:
        """The source's own line of a statement (its main lines), or None."""
        key = match_key(label)
        return next(
            (
                x for x in self.source.lines
                if x.statement == statement and x.level == "main" and match_key(x.label) == key
            ),
            None,
        )  # fmt: skip

    def unadjusted(self) -> Decimal:
        return sum(self.forex(), ZERO)

    def ordered_groups(self, natures: tuple[str, ...]) -> list[_Group]:
        found = [g for g in self.groups.values() if g.nature in natures]
        return sorted(found, key=lambda g: (NATURE_ORDER.get(g.nature or "", 9), g.id))


def figures(
    session: Session, entity_id: int, source: SourceStatements, tolerance: Decimal = ZERO
) -> Figures:
    """Our books as of the source's date, with the source's figures."""
    ledgers, groups = _books(session, entity_id, source.as_of)
    return Figures(ledgers, groups, source, tolerance)


def build(
    session: Session, entity_id: int, source: SourceStatements, tolerance: Decimal = ZERO
) -> list[tuple[str | None, StatementLine]]:
    """Our three statements as of the source's date: (section, line) pairs."""
    return lines_for(figures(session, entity_id, source, tolerance))


def lines_for(f: Figures) -> list[tuple[str | None, StatementLine]]:
    """Our three statements from figures already read: `build` without the database (the
    fx-rules finder lays them out again with other revalued figures, workers/fx_rules.py)."""
    return [*trial_balance(f), *_profit_loss(f), *_balance_sheet(f, net_profit(f))]


def net_profit(f: Figures) -> Decimal:
    """The period's result as our Profit & Loss shows it (canonical: a loss is positive)."""
    return sum((line.amount for _, line in _profit_loss(f) if line.level == "main"), ZERO)


def trial_balance(f: Figures) -> list[tuple[str | None, StatementLine]]:
    """One line per primary group, split into debit and credit ledger by ledger, a group the
    source nets for reporting counting as one figure."""
    by_group: dict[int, dict[tuple[str, object], Decimal]] = defaultdict(dict)
    for ledger in f.counted():
        units = by_group[ledger.top]
        unit = f.unit(ledger)
        units[unit] = units.get(unit, ZERO) + f.value(ledger)
    if f.replaces_stock and f.source.opening_stock is not None:
        stock = f.stock_group()
        if stock is not None:  # the stock at its opening value, where the stock ledgers sit
            unit = next((f.unit(x) for x in f.ledgers if x.kind == "stock"), ("stock", 0))
            units = by_group[stock]
            units[unit] = units.get(unit, ZERO) + f.source.opening_stock
    lines = []
    for group in f.ordered_groups(tuple(NATURE_ORDER)):
        values = list(by_group.get(group.id, {}).values())
        if values:
            lines.extend(_group_line(f, group, _tb_line(group.name, values)))
    for ledger in f.ledgers:
        if ledger.key in f.source.profit_carriers and ledger.balance:
            lines.append(_tb_line(ledger.name, [ledger.balance]))
    if any(f.forex()):  # one line: the losses as its debit, the gains as its credit
        lines.append(replace(_tb_line(COMPUTED_FOREX, f.forex()), level="detail"))
    taken = f.source_line("trial_balance", UNADJUSTED_FOREX)
    if taken is not None:
        lines.append(
            StatementLine(
                "trial_balance", UNADJUSTED_FOREX + TAKEN, "main",
                taken.amount, taken.debit, taken.credit,
            )
        )  # fmt: skip
    total = sum((line.amount for line in lines if line.level == "main"), ZERO)
    if total:  # ours don't balance: the difference in opening balances, as a note
        lines.append(StatementLine("trial_balance", OPENING_DIFFERENCE, "detail", -total))
    return [(None, line) for line in lines]


def _group_line(f: Figures, group: _Group, ours: StatementLine) -> list[StatementLine]:
    """A group's line: ours, or (ADR-043 stopgap) the source's where the group holds
    foreign-currency ledgers, the source shows its forex line and ours differs by more than
    the tolerance; then ours follows as a "(computed)" detail line and the gap as the
    "Forex revaluation difference (per Tally, under review)" detail line."""
    theirs = f.foreign_group_from_source(ours.statement, group)
    if theirs is None or not _differs(ours, theirs, f.tolerance):
        return [ours]
    gap = StatementLine(
        ours.statement, REVALUATION_DIFFERENCE, "detail", theirs.amount - ours.amount,
        _less(theirs.debit, ours.debit), _less(theirs.credit, ours.credit),
    )  # fmt: skip
    return [
        replace(theirs, label=group.name + TAKEN, level="main"),
        replace(ours, label=group.name + COMPUTED, level="detail"),
        gap,
    ]


def _differs(ours: StatementLine, theirs: StatementLine, tolerance: Decimal) -> bool:
    """By more than the tolerance in any part compared (a trial balance line's debit or
    credit; otherwise its amount), as `compare` does."""
    return any(
        abs((getattr(ours, part) or ZERO) - (getattr(theirs, part) or ZERO)) > tolerance
        for part in _parts(ours.statement)
    )


def _less(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None and b is None else (a or ZERO) - (b or ZERO)


def _tb_line(label: str, values: list[Decimal]) -> StatementLine:
    debit = sum((v for v in values if v > 0), ZERO)
    credit = -sum((v for v in values if v < 0), ZERO)
    return StatementLine("trial_balance", label, "main", debit - credit, debit, credit)


def _profit_loss(f: Figures) -> list[tuple[str | None, StatementLine]]:
    totals = f.totals()
    groups = f.ordered_groups(("income", "expense"))
    gross = [g for g in groups if g.affects_gross_profit]
    purchases = [g for g in gross if g.standard_code == PURCHASES]
    # Cost of Sales as the source lays it out: where it reports stock, or shows the block
    # (with no stock it may show none: then stock counts as zero).
    has_stock = (
        f.source.opening_stock is not None
        or f.source.closing_stock is not None
        or f.source_line("profit_loss", COST_OF_SALES) is not None
    )
    lines: list[tuple[str | None, StatementLine]] = []

    def main(section: str, label: str, amount: Decimal) -> None:
        lines.append((section, StatementLine("profit_loss", label, "main", amount)))

    def sub(label: str, amount: Decimal) -> None:
        lines.append(("gross", StatementLine("profit_loss", label, "sub", amount)))

    for group in gross:
        if group.nature == "income":
            main("gross", group.name, totals[group.id])
    expenses = [g for g in gross if g.nature == "expense"]
    if has_stock:  # Cost of Sales: stock, purchases, then the other direct expenses
        opening = f.source.opening_stock or ZERO
        closing = f.source.closing_stock or ZERO
        direct = [g for g in expenses if g not in purchases]
        spent = sum((totals[g.id] for g in expenses), ZERO)
        main("gross", "Cost of Sales :", opening + spent - closing)
        sub("Opening Stock", opening)
        for group in purchases:
            sub(f"Add: {group.name}", totals[group.id])
        sub(CLOSING_STOCK_LINE, closing)
        for group in direct:
            sub(group.name, totals[group.id])
    else:
        for group in expenses:
            main("gross", group.name, totals[group.id])
    gross_profit = sum((line.amount for _, line in lines if line.level == "main"), ZERO)
    lines.append(("gross", StatementLine("profit_loss", GROSS_PROFIT, "detail", gross_profit)))
    for group in groups:
        if not group.affects_gross_profit:
            main("net", group.name, totals[group.id])
    net = sum((line.amount for _, line in lines if line.level == "main"), ZERO)
    lines.append(("net", StatementLine("profit_loss", NET_PROFIT, "detail", net)))
    return lines


def _balance_sheet(f: Figures, net: Decimal) -> list[tuple[str | None, StatementLine]]:
    totals = f.totals()
    stock = f.stock_group()
    if f.replaces_stock and stock is not None:
        totals[stock] += f.source.closing_stock or ZERO  # the stock at its closing value
    lines: list[tuple[str | None, StatementLine]] = []
    for group in f.ordered_groups(("equity", "liability", "asset")):
        section = "assets" if group.nature == "asset" else "liabilities"
        line = StatementLine("balance_sheet", group.name, "main", totals[group.id])
        lines.extend((section, x) for x in _group_line(f, group, line))
    carried = sum((x.balance for x in f.ledgers if x.key in f.source.profit_carriers), ZERO)
    account = carried + net
    side = _side(account)
    lines.append((side, StatementLine("balance_sheet", PROFIT_LOSS_ACCOUNT, "main", account)))
    lines.append((side, StatementLine("balance_sheet", "Opening Balance", "detail", carried)))
    lines.append((side, StatementLine("balance_sheet", "Current Period", "detail", net)))
    unadjusted = f.unadjusted()
    if unadjusted:
        computed = StatementLine("balance_sheet", COMPUTED_FOREX, "detail", unadjusted)
        lines.append((_side(unadjusted), computed))
    taken = f.source_line("balance_sheet", UNADJUSTED_FOREX)
    if taken is not None:
        line = StatementLine("balance_sheet", UNADJUSTED_FOREX + TAKEN, "main", taken.amount)
        lines.append((_side(taken.amount), line))
    total = sum((line.amount for _, line in lines if line.level == "main"), ZERO)
    if total:
        lines.append(
            (_side(-total), StatementLine("balance_sheet", OPENING_DIFFERENCE, "detail", -total))
        )
    return lines


def _side(amount: Decimal) -> str:
    """Balance sheet side by sign: a credit on the liabilities side, a debit on the assets."""
    return "liabilities" if amount < 0 else "assets"


# --- comparing ----------------------------------------------------------------------------


def compare(
    ours: list[StatementLine], theirs: list[StatementLine], tolerance: Decimal = ZERO
) -> tuple[int, list[Difference]]:
    """Line by line (by match key, a missing line counting as zero) and in total, per
    statement: (lines and totals compared, differences). Trial balance lines compare their
    debit and credit; the others their amount. `detail` lines aren't compared."""
    compared, differences = 0, []
    for statement in ("trial_balance", "profit_loss", "balance_sheet"):
        mine = _by_key(ours, statement)
        source = _by_key(theirs, statement)
        for key in sorted(set(mine) | set(source)):
            a, b = mine.get(key), source.get(key)
            label = (a or b)[0]
            kind = "missing_ours" if a is None else "missing_source" if b is None else "amount"
            for part in _parts(statement):
                x = a[1][part] if a else ZERO
                y = b[1][part] if b else ZERO
                compared += 1
                if abs(x - y) > tolerance:
                    differences.append(
                        Difference(statement, f"{key}:{part}", label, x, y, part, kind)
                    )
        for part in _parts(statement):
            x = sum((v[1][part] for v in mine.values()), ZERO)
            y = sum((v[1][part] for v in source.values()), ZERO)
            compared += 1
            if abs(x - y) > tolerance:
                differences.append(
                    Difference(statement, f"total:{part}", "total", x, y, part, "total")
                )
    return compared, differences


def _parts(statement: str) -> tuple[str, ...]:
    return ("debit", "credit") if statement == "trial_balance" else ("amount",)


def _by_key(
    lines: list[StatementLine], statement: str
) -> dict[str, tuple[str, dict[str, Decimal]]]:
    found: dict[str, tuple[str, dict[str, Decimal]]] = {}
    for line in lines:
        if line.statement != statement or line.level == "detail":
            continue
        key = match_key(line.label)
        label, parts = found.get(key, (line.label, {"amount": ZERO, "debit": ZERO, "credit": ZERO}))
        parts["amount"] += line.amount
        parts["debit"] += line.debit or ZERO
        parts["credit"] += line.credit or ZERO
        found[key] = (label, parts)
    return found


# --- storing and the whole refresh -------------------------------------------------------


def stored_stock(
    session: Session, entity_id: int, as_of: date
) -> tuple[Decimal | None, Decimal | None] | None:
    """The total stock value stored for a date (opening, closing), or None."""
    row = session.execute(
        select(A.StockValue.opening_value, A.StockValue.closing_value).where(
            A.StockValue.entity_id == entity_id,
            A.StockValue.as_of == as_of,
            A.StockValue.scope == "total",
        )
    ).first()
    return (row[0], row[1]) if row else None


def refresh(
    session: Session,
    entity_id: int,
    connection_id: int,
    origin: str,
    source: SourceStatements,
    tolerance: Decimal = ZERO,
) -> Comparison:
    """Stores the source's figures for the date (stock values, revaluations, its statement
    lines), builds and stores ours, and compares them. Returns what was compared and the
    stock value stored before (to check it against the source's)."""
    result = Comparison(source.as_of, stock_before=stored_stock(session, entity_id, source.as_of))
    now = utcnow()
    _store_stock(session, entity_id, connection_id, origin, source, now)
    _store_revaluations(session, entity_id, connection_id, origin, source, now)
    ours = build(session, entity_id, source, tolerance)
    _store_lines(
        session, entity_id, source.as_of, "source", [(_section(x), x) for x in source.lines], now
    )
    _store_lines(session, entity_id, source.as_of, "ours", ours, now)
    result.compared, result.differences = compare(
        [x for _, x in ours], list(source.lines), tolerance
    )
    result.taken = taken_differences([x for _, x in ours], tolerance)
    session.commit()
    return result


def taken_differences(lines: list[StatementLine], tolerance: Decimal = ZERO) -> list[Difference]:
    """Lines taken from the source whose figure differs from ours computed beside them
    (kind "taken"): not a statement difference, but what the summary tests to find the
    rule."""
    by_label = {(x.statement, x.label): x for x in lines}
    found = []
    for line in lines:
        if not line.label.endswith(TAKEN):
            continue
        base = line.label.removesuffix(TAKEN)
        computed = by_label.get((line.statement, base + COMPUTED))
        for part in _parts(line.statement):
            ours = (getattr(computed, part) or ZERO) if computed else ZERO
            theirs = getattr(line, part) or ZERO
            if abs(ours - theirs) > tolerance:
                key = f"{match_key(base)}:{part}"
                found.append(Difference(line.statement, key, base, ours, theirs, part, "taken"))
    return found


def _section(line: StatementLine) -> str | None:
    return _side(line.amount) if line.statement == "balance_sheet" else None


def _store_stock(
    session: Session,
    entity_id: int,
    connection_id: int,
    origin: str,
    source: SourceStatements,
    now: object,
) -> None:
    session.execute(
        delete(A.StockValue).where(
            A.StockValue.entity_id == entity_id, A.StockValue.as_of == source.as_of
        )
    )
    for figure in source.stock:
        session.add(
            A.StockValue(
                entity_id=entity_id,
                connection_id=connection_id,
                origin=origin,
                as_of=source.as_of,
                scope=figure.scope,
                scope_name=figure.name[:255],
                opening_value=figure.opening,
                closing_value=figure.closing,
                integrated=source.integrated if figure.scope == "total" else None,
                read_at=now,
            )
        )


def _store_revaluations(
    session: Session,
    entity_id: int,
    connection_id: int,
    origin: str,
    source: SourceStatements,
    now: object,
) -> None:
    session.execute(
        delete(A.FxRevaluationSnapshot).where(
            A.FxRevaluationSnapshot.entity_id == entity_id,
            A.FxRevaluationSnapshot.as_of == source.as_of,
        )
    )
    if not source.revalued:
        return
    ledgers, _ = _books(session, entity_id, source.as_of)
    for ledger in ledgers:
        if ledger.key in source.revalued:
            revalued = source.revalued[ledger.key]
            session.add(
                A.FxRevaluationSnapshot(
                    entity_id=entity_id,
                    ledger_id=ledger.id,
                    connection_id=connection_id,
                    origin=origin,
                    as_of=source.as_of,
                    book_value=ledger.balance,
                    revalued_value=revalued,
                    unrealised_gain_loss=ledger.balance - revalued,
                    read_at=now,
                )
            )


def _store_lines(
    session: Session,
    entity_id: int,
    as_of: date,
    figures: str,
    lines: list[tuple[str | None, StatementLine]],
    now: object,
) -> None:
    session.execute(
        delete(LineRow).where(
            LineRow.entity_id == entity_id, LineRow.as_of == as_of, LineRow.figures == figures
        )
    )
    for n, (section, line) in enumerate(lines, start=1):
        session.add(
            LineRow(
                entity_id=entity_id,
                as_of=as_of,
                statement=line.statement,
                figures=figures,
                line_no=n,
                section=section,
                label=line.label[:255],
                match_key=match_key(line.label)[:255],
                level=line.level,
                amount=line.amount,
                debit=line.debit,
                credit=line.credit,
                refreshed_at=now,
            )
        )
