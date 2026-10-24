"""Which revaluation rule the source's statements follow: the fx-rules finder (ADR-043,
FX-004). Source-independent.

Where it fits: `./dev.ps1 statements` stored the source's own statement lines, stock values
and revalued balances at every month end (core/statements.py). For each of those dates this
module lays out our Trial Balance and Balance Sheet again, with the same code
(`statements.lines_for`, so netting, sides and stock are identical), once per candidate
rule: each foreign-currency ledger's revalued value = its foreign balance at the date
(core/fx.py) × the rule's rate. It then counts at how many dates the groups holding
foreign-currency ledgers (e.g. Current Assets) and the Unadjusted Forex Gain/Loss line
equal the source's, exactly (to the paisa) and within 1. Counts only: never names or
amounts.

"as exported" lays the lines out with the revalued balances the source's ledger-balance
export gave (what the statements use today): its counts must equal the statements'
results, which proves the stored figures are read back faithfully. Profit carriers (ledgers
directly under Primary) aren't needed: they never sit in those groups or that line.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.base import SourceStatements, StatementLine
from core import fx, statements
from core.models import accounting as A  # noqa: N812
from core.models.reporting import StatementLine as LineRow

ZERO = Decimal(0)
CENT = Decimal("0.01")
NEAR = Decimal(1)
EDUCATIONAL_DAYS = frozenset({1, 2, 31})  # core/dates.py: Educational mode's reliable days
TB, BS = "trial_balance", "balance_sheet"


class Rates:
    """The entity's rates by currency (as the source names it) and kind, sorted by date."""

    def __init__(self, session: Session, entity_id: int) -> None:
        self.by: dict[tuple[str, str], list[tuple[date, Decimal]]] = defaultdict(list)
        for name, kind, on, rate in session.execute(
            select(
                A.ExchangeRate.currency_name,
                A.ExchangeRate.rate_kind,
                A.ExchangeRate.rate_date,
                A.ExchangeRate.rate,
            )
            .where(A.ExchangeRate.entity_id == entity_id)
            .order_by(A.ExchangeRate.rate_date)
        ):
            self.by[(name, kind)].append((on, Decimal(rate)))

    def kinds(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for (_, kind), rates in self.by.items():
            counts[kind] += len(rates)
        return dict(counts)

    def exact(self, name: str, kind: str, on: date) -> Decimal | None:
        return next((r for d, r in self.by.get((name, kind), []) if d == on), None)

    def on_or_before(
        self, name: str, kind: str, on: date, days: frozenset[int] | None = None
    ) -> Decimal | None:
        found = None
        for d, r in self.by.get((name, kind), []):
            if d > on:
                break
            if days is None or d.day in days:
                found = r
        return found

    def first(self, name: str, kind: str) -> Decimal | None:
        rates = self.by.get((name, kind), [])
        return rates[0][1] if rates else None

    def latest(self, name: str, kind: str) -> Decimal | None:
        rates = self.by.get((name, kind), [])
        return rates[-1][1] if rates else None


RateOf = Callable[[Rates, str, date], Decimal | None]


CALIBRATION = "as exported (calibration)"


@dataclass(frozen=True)
class Rule:
    name: str
    rate: RateOf | None = None  # None: one of the two rules below
    exported: bool = False  # the source's own revalued balances (the calibration)
    book: bool = False  # no revaluation: book value


def rules(rates: Rates) -> list[Rule]:
    """The candidate rules, for the rate kinds the entity has."""
    found = [Rule(CALIBRATION, exported=True), Rule("book value", book=True)]
    kinds = rates.kinds()
    for kind in ("standard", "selling", "buying"):
        if kinds.get(kind):
            found += [
                Rule(f"list {kind}, exact date", lambda r, n, d, k=kind: r.exact(n, k, d)),
                Rule(f"list {kind}, on or before", lambda r, n, d, k=kind: r.on_or_before(n, k, d)),
                Rule(
                    f"list {kind}, on or before, days 1/2/31",
                    lambda r, n, d, k=kind: r.on_or_before(n, k, d, EDUCATIONAL_DAYS),
                ),
                Rule(f"list {kind}, first", lambda r, n, d, k=kind: r.first(n, k)),
                Rule(f"list {kind}, latest", lambda r, n, d, k=kind: r.latest(n, k)),
            ]
    if kinds.get("vouchers"):
        found += [
            Rule("voucher rate, exact date", lambda r, n, d: r.exact(n, "vouchers", d)),
            Rule("voucher rate, on or before", lambda r, n, d: r.on_or_before(n, "vouchers", d)),
        ]
    return found


@dataclass
class Result:
    """One rule variant's counts over the dates."""

    rule: str
    variant: str
    groups_exact: int = 0
    groups_near: int = 0
    forex_exact: int = 0
    forex_near: int = 0
    no_rate: int = 0  # ledger-dates left at book value for want of a rate


@dataclass
class Finding:
    dates: int = 0
    dates_unreadable: int = 0  # dates without the source's stored lines
    foreign_ledgers: int = 0  # the source revalues them
    other_ledgers_with_foreign_figures: int = 0  # kept in the base currency
    groups: int = 0  # groups holding foreign-currency ledgers
    rate_kinds: dict[str, int] = field(default_factory=dict)
    results: list[Result] = field(default_factory=list)


def stored_source(
    session: Session, entity_id: int, on: date, netted: frozenset[str]
) -> SourceStatements | None:
    """The source's statements at a date as `statements` stored them; None without them."""
    lines = tuple(
        StatementLine(statement, label, level, Decimal(amount), _dec(debit), _dec(credit))
        for statement, label, level, amount, debit, credit in session.execute(
            select(
                LineRow.statement, LineRow.label, LineRow.level, LineRow.amount,
                LineRow.debit, LineRow.credit,
            )
            .where(LineRow.entity_id == entity_id, LineRow.as_of == on, LineRow.figures == "source")
            .order_by(LineRow.line_no)
        )
    )  # fmt: skip
    if not lines:
        return None
    stock = session.execute(
        select(
            A.StockValue.opening_value, A.StockValue.closing_value, A.StockValue.integrated
        ).where(
            A.StockValue.entity_id == entity_id,
            A.StockValue.as_of == on,
            A.StockValue.scope == "total",
        )
    ).first()
    revalued = dict(
        session.execute(
            select(A.Ledger.source_key, A.FxRevaluationSnapshot.revalued_value)
            .join(A.Ledger, A.Ledger.id == A.FxRevaluationSnapshot.ledger_id)
            .where(
                A.FxRevaluationSnapshot.entity_id == entity_id,
                A.FxRevaluationSnapshot.as_of == on,
            )
        ).all()
    )
    return SourceStatements(
        as_of=on,
        lines=lines,
        opening_stock=stock[0] if stock else None,
        closing_stock=stock[1] if stock else None,
        revalued={k: Decimal(v) for k, v in revalued.items()},
        integrated=stock[2] if stock else None,
        netted_groups=netted,
    )


def _dec(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def find(session: Session, entity_id: int, dates: list[date], netted: frozenset[str]) -> Finding:
    """Every candidate rule's matches over the dates (see the module docstring)."""
    rates = Rates(session, entity_id)
    candidates = rules(rates)
    finding = Finding(rate_kinds=rates.kinds())
    results: dict[tuple[str, str], Result] = {}
    foreign: set[str] = set()
    others: set[str] = set()
    groups_seen: set[int] = set()
    for on in dates:
        source = stored_source(session, entity_id, on, netted)
        if source is None:
            finding.dates_unreadable += 1
            continue
        finding.dates += 1
        f = statements.figures(session, entity_id, source)
        by_id = fx.foreign_balances(session, entity_id, on)
        balances = {x.key: by_id[x.id] for x in f.ledgers if x.id in by_id}
        groups = {x.top for x in f.ledgers if x.key in source.revalued}
        groups_seen |= groups
        foreign |= set(source.revalued)
        others |= set(balances) - set(source.revalued)
        theirs = _parts(source.lines, f, groups, taken_ok=False)
        for rule in candidates:
            for variant in _variants(rule):
                revalued, missing = _revalued(rule, variant, f, source, balances, rates, on)
                laid = replace(f, source=replace(source, revalued=revalued))
                ours = _parts([x for _, x in statements.lines_for(laid)], f, groups, taken_ok=True)
                result = results.setdefault((rule.name, variant), Result(rule.name, variant))
                result.no_rate += missing
                rounded = variant.endswith("total")
                _count(result, ours, theirs, rounded)
    finding.foreign_ledgers = len(foreign)
    finding.other_ledgers_with_foreign_figures = len(others)
    finding.groups = len(groups_seen)
    finding.results = sorted(
        results.values(), key=lambda r: (-r.groups_exact, -r.forex_exact, -r.groups_near, r.rule)
    )
    return finding


THEIRS_ONLY = "the source's foreign ledgers"
WITH_OTHERS = "also base-currency ledgers with foreign figures"


def _variants(rule: Rule) -> list[str]:
    if rule.exported or rule.book:
        return [THEIRS_ONLY]
    return [
        f"{ledgers}, rounded per {rounding}"
        for ledgers in (THEIRS_ONLY, WITH_OTHERS)
        for rounding in ("ledger", "total")
    ]


def _revalued(
    rule: Rule,
    variant: str,
    f: statements.Figures,
    source: SourceStatements,
    balances: dict[str, fx.ForeignBalance],
    rates: Rates,
    on: date,
) -> tuple[dict[str, Decimal], int]:
    """(each revalued ledger's value under the rule, ledger-dates without a rate)."""
    if rule.exported:
        return dict(source.revalued), 0
    book = {x.key: x.balance for x in f.ledgers}
    keys = set(source.revalued)
    if variant.startswith("also"):
        keys |= set(balances)
    if rule.book:
        return {k: book[k] for k in keys if k in book}, 0
    found, missing = {}, 0
    for key in keys:
        balance = balances.get(key)
        if balance is None or not balance.balance_fc:
            found[key] = ZERO  # nothing in a foreign currency: the source revalues it to 0
            continue
        rate = rule.rate(rates, balance.currency_name or "", on) if rule.rate else None
        if rate is None:
            found[key] = book.get(key, ZERO)
            missing += 1
            continue
        value = balance.balance_fc * rate
        found[key] = value.quantize(CENT) if variant.endswith("ledger") else value
    return found, missing


Parts = dict[str, Decimal]


def _parts(
    lines: list[StatementLine] | tuple[StatementLine, ...],
    f: statements.Figures,
    groups: set[int],
    taken_ok: bool,
) -> tuple[Parts, Parts]:
    """(the groups' parts, the forex line's parts) of one side: Trial Balance debit and
    credit and Balance Sheet amount. Ours (`taken_ok`) read a group's or the forex line's
    "(computed)" detail line where the line itself was taken from the source."""
    keys = {statements.match_key(f.groups[g].name): f.groups[g].name for g in groups}
    forex_key = statements.match_key(statements.UNADJUSTED_FOREX)
    group_parts: Parts = defaultdict(lambda: ZERO)
    forex_parts: Parts = defaultdict(lambda: ZERO)
    for line in lines:
        computed = line.label.endswith(statements.COMPUTED)
        if line.level == "detail" and not (taken_ok and computed):
            continue
        if line.level != "detail" and line.label.endswith(statements.TAKEN):
            continue  # the source's figure: ours is its "(computed)" line
        key = statements.match_key(line.label)
        target = forex_parts if key == forex_key else group_parts if key in keys else None
        if target is None:
            continue
        prefix = f"{line.statement}:{key}"
        if line.statement == TB:
            target[f"{prefix}:debit"] += line.debit or ZERO
            target[f"{prefix}:credit"] += line.credit or ZERO
        elif line.statement == BS:
            target[f"{prefix}:amount"] += line.amount
    return group_parts, forex_parts


def _count(
    result: Result, ours: tuple[Parts, Parts], theirs: tuple[Parts, Parts], rounded: bool
) -> None:
    for side, (exact, near) in (
        (0, ("groups_exact", "groups_near")),
        (1, ("forex_exact", "forex_near")),
    ):
        a, b = ours[side], theirs[side]
        gaps = [
            abs((a.get(k, ZERO).quantize(CENT) if rounded else a.get(k, ZERO)) - b.get(k, ZERO))
            for k in set(a) | set(b)
        ]
        if all(g < Decimal("0.005") for g in gaps):
            setattr(result, exact, getattr(result, exact) + 1)
        if all(g <= NEAR for g in gaps):
            setattr(result, near, getattr(result, near) + 1)
