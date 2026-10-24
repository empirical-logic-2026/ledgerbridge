"""What the differences between our statements and the source's own equal, summarised so the
summary can be shared from a client's machine (ADR-040; VAL-015, RPT-012). Source-independent.

Where it fits: core/statements.py compares our Trial Balance, Profit & Loss and Balance
Sheet with the source's at a date. Validation (core/validation.py) and the statements
command (workers/statements.py) pass each date's comparison to a `Summary`, which records,
for every line that differs:

- a label safe to show: the statements' own lines and the source's reserved group names as
  they are; any other group as "a custom group under <its nearest reserved group>" (or
  "<reserved name> (renamed)"), a ledger directly under Primary as such;
- whether the line is missing on one side or has a different amount;
- which tested amounts the difference equals (Direct Expenses, Direct Incomes, the stock
  values and the stock gap, the foreign-currency revaluation, Profit & Loss A/c's own
  balance, the profit and stock at the last year end, ...).

`Summary.lines()` gives one line per statement line and kind with the number of dates and
of the dates each tested amount explains: counts, standard names and kinds only, never
other names or amounts.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.base import SourceStatements
from core.dates import financial_year_ends
from core.models import accounting as A  # noqa: N812
from core.statements import (
    OPENING_DIFFERENCE,
    PROFIT_LOSS_ACCOUNT,
    PURCHASES,
    UNADJUSTED_FOREX,
    Comparison,
    Difference,
    Figures,
    figures,
    match_key,
    net_profit,
    trial_balance,
)

ZERO = Decimal(0)
SALES = "4110"  # the standard account of sales groups
STATEMENTS = {"trial_balance": "Trial balance", "profit_loss": "Profit & loss",
              "balance_sheet": "Balance sheet"}  # fmt: skip
KINDS = {
    "amount": "different amount",
    "missing_ours": "missing in ours",
    "missing_source": "missing in the source's",
    "total": "different total",
}
# Our own lines (core/statements.py): safe to show like the source's.
OUR_LINES = (PROFIT_LOSS_ACCOUNT, UNADJUSTED_FOREX, OPENING_DIFFERENCE, "Cost of Sales",
             "Opening Stock", "Closing Stock", "Opening Balance", "Current Period")  # fmt: skip
PREFIXES = ("Add: ", "Less: ")


# --- labels safe to show ----------------------------------------------------------------


class Labels:
    """Statement labels as they may be shown outside the client's machine."""

    def __init__(self, session: Session, entity_id: int, f: Figures) -> None:
        standard = f.source.standard_names
        self.safe = {match_key(name) for name in (*standard, *OUR_LINES)}
        self.reserved = {match_key(name): name for name in standard}
        self.tree: dict[int, tuple[int | None, str, list[str]]] = {
            gid: (parent, name, list((extra or {}).get("_aliases") or []))
            for gid, parent, name, extra in session.execute(
                select(
                    A.AccountGroup.id,
                    A.AccountGroup.parent_id,
                    A.AccountGroup.name,
                    A.AccountGroup.extra,
                ).where(A.AccountGroup.entity_id == entity_id)
            )
        }
        self.groups: dict[str, int] = {}
        for gid, (_, name, aliases) in self.tree.items():
            for candidate in (*aliases, name):  # the current name wins over an alias
                self.groups[match_key(candidate)] = gid
        self.carriers = {match_key(x.name) for x in f.ledgers if x.key in f.source.profit_carriers}

    def shown(self, label: str) -> str:
        if label == "total":
            return label
        key = match_key(label)
        if key in self.safe:
            return " ".join(label.split()).rstrip(" :")
        prefix = next((p for p in PREFIXES if label.startswith(p)), "")
        if key in self.groups:
            return prefix + self._group(self.groups[key])
        if key in self.carriers:
            return prefix + "a ledger directly under Primary"
        return "a line not recognised"

    def _group(self, gid: int) -> str:
        for alias in self.tree[gid][2]:  # a reserved group the user renamed
            if match_key(alias) in self.reserved:
                return f"{self.reserved[match_key(alias)]} (renamed)"
        seen, parent = {gid}, self.tree[gid][0]
        while parent in self.tree and parent not in seen:
            seen.add(parent)
            above, name, names = self.tree[parent]
            for candidate in (name, *names):
                if match_key(candidate) in self.reserved:
                    return f"a custom group under {self.reserved[match_key(candidate)]}"
            parent = above
        return "a custom group under Primary"


# --- tested amounts -----------------------------------------------------------------------


@dataclass
class YearEnd:
    """The last financial year end before the date: our profit up to it and the stock value
    stored for it (None when unknown)."""

    profit: Decimal | None = None
    stock: Decimal | None = None


def tested_amounts(f: Figures, year_end: YearEnd) -> dict[str, Decimal]:
    """The amounts a difference is tested against, by name (canonical sign: debit, loss and
    expense positive). Zero and unknown amounts are left out."""
    source = f.source
    totals = f.totals()
    gross = [g for g in f.groups.values() if g.affects_gross_profit]
    stock = [x for x in f.ledgers if x.kind == "stock"]
    stock_opening = sum((x.opening for x in stock), ZERO)
    stock_closing = sum((x.balance for x in stock), ZERO)
    items = source.item_values or (
        (source.opening_stock, source.closing_stock) if f.integrated else (None, None)
    )
    forex = f.forex()
    net = net_profit(f)
    found: dict[str, Decimal | None] = {
        "Direct Expenses": sum(
            (totals[g.id] for g in gross if g.nature == "expense" and g.standard_code != PURCHASES),
            ZERO,
        ),
        "Direct Incomes": sum(
            (totals[g.id] for g in gross if g.nature == "income" and g.standard_code != SALES),
            ZERO,
        ),
        "the opening stock": source.opening_stock,
        "the closing stock": source.closing_stock,
        "the stock ledgers' opening": stock_opening,
        "the stock ledgers' closing": stock_closing,
        "the stock gap at the books' beginning": _less(items[0], stock_opening),
        "the stock gap at the date": _less(items[1], stock_closing),
        "the foreign-currency revaluation": sum(forex, ZERO),
        "the foreign-currency losses": sum((x for x in forex if x > 0), ZERO),
        "the foreign-currency gains": sum((x for x in forex if x < 0), ZERO),
        "the source's Unadjusted Forex Gain/Loss": sum(
            (
                x.amount
                for x in source.lines
                if x.statement == "balance_sheet" and _is_forex(x.label)
            ),
            ZERO,
        ),
        "Profit & Loss A/c's own balance": sum(
            (x.balance for x in f.ledgers if x.key in source.profit_carriers), ZERO
        ),
        "the net profit": net,
        "the difference in opening balances": sum(
            (x.amount for _, x in trial_balance(f) if x.label == OPENING_DIFFERENCE), ZERO
        ),
        "the profit up to the last year end": year_end.profit,
        "the profit since the last year end": _less(net, year_end.profit),
        "the stock at the last year end": year_end.stock,
        "the stock at the last year end less the opening stock": _less(
            year_end.stock, source.opening_stock
        ),
        "the foreign-currency ledgers' openings": sum(
            (x.opening for x in f.ledgers if x.key in source.revalued), ZERO
        ),
        **{
            f"the closing stock less {name}": _less(source.closing_stock, amount)
            for name, amount in source.stock_candidates.items()
        },
    }
    return {name: amount for name, amount in found.items() if amount}


NETTED = "the split with each sub-group netted"


def netted_split(f: Figures, group_id: int) -> dict[str, Decimal]:
    """A Trial Balance group line's debit and credit if each sub-group directly under the
    group were netted first (ledgers directly in the group stay one by one); ours splits
    ledger by ledger, as recorded on the test company (2026-10-23)."""
    sums: dict[object, Decimal] = defaultdict(lambda: ZERO)
    for x in f.counted():
        if x.top == group_id:
            sums[("group", x.branch) if x.branch else ("ledger", x.id)] += f.value(x)
    if f.integrated and f.source.opening_stock is not None and f.stock_group() == group_id:
        branch = next((x.branch for x in f.ledgers if x.kind == "stock"), None)
        sums[branch if branch is not None else "stock"] += f.source.opening_stock
    return {
        "debit": sum((v for v in sums.values() if v > 0), ZERO),
        "credit": -sum((v for v in sums.values() if v < 0), ZERO),
    }


def _is_forex(label: str) -> bool:
    return match_key(label) == match_key(UNADJUSTED_FOREX)


def _less(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None else a - b


def equals(difference: Decimal, tested: dict[str, Decimal], tolerance: Decimal) -> list[str]:
    """The tested amounts the difference equals (or equals with the opposite sign)."""
    found = []
    for name, amount in tested.items():
        if abs(difference - amount) <= tolerance:
            found.append(name)
        elif abs(difference + amount) <= tolerance:
            found.append(f"minus {name}")
    return found


def last_year_end(session: Session, entity_id: int, f: Figures) -> YearEnd:
    """Our profit up to the last financial year end before the date, and the stock value
    stored for it (the statements of a year end store it; in Educational mode the year
    end may be read a day or two later, core/dates.py)."""
    entity = session.get(A.Entity, entity_id)
    if entity is None:
        return YearEnd()
    ends = financial_year_ends(entity.books_from, entity.fy_start_month, f.source.as_of)
    if not ends:
        return YearEnd()
    end = ends[-1]
    stored = session.execute(
        select(A.StockValue.as_of, A.StockValue.closing_value)
        .where(
            A.StockValue.entity_id == entity_id,
            A.StockValue.scope == "total",
            A.StockValue.as_of.between(end, end + timedelta(days=2)),
        )
        .order_by(A.StockValue.as_of)
        .limit(1)
    ).first()
    has_stock = f.source.opening_stock is not None or f.source.closing_stock is not None
    if has_stock and stored is None:
        return YearEnd()  # the profit then needs the stock value: unknown
    on, stock = (stored[0], stored[1]) if stored else (end, None)
    then = replace(f.source, as_of=on, closing_stock=stock)
    return YearEnd(net_profit(figures(session, entity_id, then)), stock)


# --- the summary --------------------------------------------------------------------------


@dataclass
class _Row:
    dates: set[date] = field(default_factory=set)
    equals: Counter[str] = field(default_factory=Counter)


@dataclass
class Summary:
    """Differing lines over several dates, with what they equal (counts only)."""

    tolerance: Decimal = ZERO
    dates: set[date] = field(default_factory=set)  # dates compared
    rows: dict[tuple[str, str, str, str], _Row] = field(default_factory=dict)

    def add(
        self, session: Session, entity_id: int, source: SourceStatements, result: Comparison
    ) -> None:
        self.dates.add(source.as_of)
        if not result.differences:
            return
        f = figures(session, entity_id, source)
        tested = tested_amounts(f, last_year_end(session, entity_id, f))
        labels = Labels(session, entity_id, f)
        close = max(self.tolerance, Decimal("0.01"))
        groups = {match_key(g.name): g.id for g in f.groups.values()}
        for difference in result.differences:
            row = self.rows.setdefault(_key(difference, labels), _Row())
            row.dates.add(source.as_of)
            line = dict(tested)
            group = groups.get(match_key(difference.label))
            if difference.statement == "trial_balance" and group is not None:
                netted = netted_split(f, group)[difference.part]
                line[NETTED] = difference.ours - netted  # the source's equals the netted split
            row.equals.update(equals(difference.ours - difference.source, line, close))

    def lines(self) -> list[str]:
        """One line per differing statement line and kind, statement by statement, the most
        frequent first."""
        order = list(STATEMENTS)
        ranked = sorted(
            self.rows.items(),
            key=lambda item: (order.index(item[0][0]), -len(item[1].dates), item[0][1:]),
        )
        out = []
        for (statement, label, part, kind), row in ranked:
            shown = label if part == "amount" else f"{label} ({part})"
            explained = (
                ", ".join(f"{name} at {n:,}" for name, n in row.equals.most_common(3))
                if row.equals
                else "no tested amount"
            )
            out.append(
                f"{STATEMENTS[statement]}: {shown}: {KINDS[kind]} at {len(row.dates):,} "
                f"of {len(self.dates):,} dates; equals {explained}"
            )
        return out


def _key(difference: Difference, labels: Labels) -> tuple[str, str, str, str]:
    return (difference.statement, labels.shown(difference.label), difference.part, difference.kind)
