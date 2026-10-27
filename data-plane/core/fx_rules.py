"""Which revaluation rule the source's statements follow: the fx-rules finder (ADR-043,
ADR-046, FX-004). Source-independent.

Where it fits: `./dev.ps1 statements` stored the source's own statement lines, stock values
and revalued balances at every month end (core/statements.py). For each of those dates this
module lays out our Trial Balance and Balance Sheet again, with the same code
(`statements.lines_for`, so netting, sides and stock are identical), once per candidate
rule: each foreign-currency ledger's revalued value = its foreign balance at the date
(core/fx.py) × the rule's rate. Counts only: never names or amounts. Three parts, so a
difference can be placed in the rate or in the layout (pilot 2026-10-26: laid out with the
source's own per-ledger figures, the groups matched at 60 of 78 dates and the forex line
at none):

1. **Per ledger:** each rule's value against the revalued balance the source's
   ledger-balance export gave, ledger-date by ledger-date (to the paisa, rounded to the
   rupee, within 1). The rate rule alone.
2. **Layout:** the source's own per-ledger figures, with the base-currency ledgers holding
   foreign figures (which that export doesn't revalue) at book value or revalued by each
   rule, and the forex line built in each form (`FORMS`, each with either sign). The
   statements' own layout with the rupee ledgers at book value is the calibration: what
   `statements` and the ADR-043 stopgap use today.
3. **Computed:** each rule throughout, with the rupee ledgers at book value or revalued too,
   in each form of the forex line. A combination matching every date in groups and forex
   line is the rule PR 2 implements (ADR-043's time-box, 2026-10-26).

Each date counts as matching when the groups holding foreign-currency ledgers (e.g. Current
Assets) and the Unadjusted Forex Gain/Loss line equal the source's, exactly (to the paisa)
or within 1. Profit carriers (ledgers directly under Primary) aren't needed: they never sit
in those groups or that line.
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
HALF_CENT = Decimal("0.005")
RUPEE = Decimal(1)
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


@dataclass(frozen=True)
class Rule:
    name: str
    rate: RateOf | None = None  # None: book value, no revaluation


BOOK = Rule("book value")


def rules(rates: Rates) -> list[Rule]:
    """The candidate rate rules, for the rate kinds the entity has."""
    found = []
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


# How the forex line is built from each ledger's book value less its revalued value (a loss
# positive): as statements.py does today (ledger by ledger, losses the debit and gains the
# credit), or netted first, in total, per currency or per primary group; each also with the
# opposite sign.
LEDGER_BY_LEDGER = "ledger by ledger"
FORMS = (LEDGER_BY_LEDGER, "netted in total", "netted per currency", "netted per group")
SIGNS = ((1, ""), (-1, ", opposite sign"))
TODAY = f"forex line {LEDGER_BY_LEDGER}"  # the statements' own layout (the calibration)

# What the base-currency ledgers with foreign figures (the source doesn't revalue them in
# its ledger-balance export) count at.
AT_BOOK = "rupee ledgers with foreign amounts at book value"


@dataclass
class LedgerResult:
    """Part 1: one rule's values against the source's own revalued balance, ledger by ledger
    and date by date (the rate rule alone, layout aside)."""

    rule: str
    compared: int = 0  # ledger-dates with a value under the rule
    exact: int = 0  # to the paisa
    rupee: int = 0  # rounded to the rupee
    near: int = 0  # within 1
    no_rate: int = 0


@dataclass
class Result:
    """Parts 2 and 3: one combination's counts over the dates (groups and forex line)."""

    rule: str  # part 2: what the rupee ledgers are revalued by; part 3: the rate rule
    variant: str  # the rupee ledgers and the forex line's form
    groups_exact: int = 0
    groups_near: int = 0
    forex_exact: int = 0
    forex_near: int = 0
    no_rate: int = 0  # ledger-dates left at book value for want of a rate

    @property
    def score(self) -> tuple[int, int, int]:
        """Best first: most dates exact on both, then groups exact, then within 1."""
        return (
            self.groups_exact + self.forex_exact,
            self.groups_exact,
            self.groups_near + self.forex_near,
        )


@dataclass
class Finding:
    dates: int = 0
    dates_unreadable: int = 0  # dates without the source's stored lines
    foreign_ledgers: int = 0  # the source revalues them
    other_ledgers_with_foreign_figures: int = 0  # kept in the base currency
    groups: int = 0  # groups holding foreign-currency ledgers
    rate_kinds: dict[str, int] = field(default_factory=dict)
    per_ledger: list[LedgerResult] = field(default_factory=list)  # part 1
    layouts: list[Result] = field(default_factory=list)  # part 2: the source's own figures
    results: list[Result] = field(default_factory=list)  # part 3: computed rules

    def calibration(self) -> Result | None:
        """The statements' own layout with the source's own figures (what `statements` and
        the ADR-043 stopgap use today)."""
        return next((r for r in self.layouts if r.rule == AT_BOOK and r.variant == TODAY), None)


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


@dataclass
class _Date:
    """One date's figures, read once and shared by every rule."""

    on: date
    f: statements.Figures
    source: SourceStatements
    balances: dict[str, fx.ForeignBalance]  # ledger key -> its foreign balance
    book: dict[str, Decimal]  # ledger key -> our balance
    tops: dict[str, int]  # ledger key -> its primary group
    groups: set[int]  # groups holding the source's foreign-currency ledgers
    theirs: tuple["Parts", "Parts"]

    @property
    def foreign(self) -> set[str]:
        """The ledgers the source revalues (and that we hold)."""
        return {k for k in self.source.revalued if k in self.book}

    @property
    def others(self) -> set[str]:
        """Base-currency ledgers with foreign figures."""
        return set(self.balances) - set(self.source.revalued)


def find(session: Session, entity_id: int, dates: list[date], netted: frozenset[str]) -> Finding:
    """The three parts' counts over the dates (see the module docstring)."""
    rates = Rates(session, entity_id)
    candidates = rules(rates)
    finding = Finding(rate_kinds=rates.kinds())
    per_ledger = {r.name: LedgerResult(r.name) for r in [BOOK, *candidates]}
    layouts: dict[tuple[str, str], Result] = {}
    results: dict[tuple[str, str], Result] = {}
    foreign: set[str] = set()
    others: set[str] = set()
    groups_seen: set[int] = set()
    for on in dates:
        d = _read(session, entity_id, on, netted)
        if d is None:
            finding.dates_unreadable += 1
            continue
        finding.dates += 1
        foreign |= d.foreign
        others |= d.others
        groups_seen |= d.groups
        for rule in [BOOK, *candidates]:
            _per_ledger(per_ledger[rule.name], rule, d, rates)
        # Part 2: the source's own per-ledger figures; the rupee ledgers at book value or
        # revalued by each rule.
        own = {k: d.source.revalued[k] for k in d.foreign}
        _tally(layouts, AT_BOOK, "", d, own, 0)
        for rule in candidates:
            extra, missing = _values(rule, d.others, d, rates)
            _tally(layouts, f'rupee ledgers with foreign amounts by "{rule.name}"', "", d,
                   own | extra, missing)  # fmt: skip
        # Part 3: computed throughout.
        for rule in [BOOK, *candidates]:
            values, missing = _values(rule, d.foreign, d, rates)
            _tally(results, rule.name, AT_BOOK, d, values, missing)
            if rule is not BOOK and d.others:
                extra, more = _values(rule, d.others, d, rates)
                _tally(results, rule.name, "rupee ledgers with foreign amounts too", d,
                       values | extra, missing + more)  # fmt: skip
    finding.foreign_ledgers = len(foreign)
    finding.other_ledgers_with_foreign_figures = len(others)
    finding.groups = len(groups_seen)
    finding.per_ledger = sorted(
        per_ledger.values(), key=lambda r: (-r.exact, -r.rupee, -r.near, r.rule)
    )
    finding.layouts = sorted(layouts.values(), key=lambda r: (_order(r), r.rule, r.variant))
    finding.results = sorted(results.values(), key=lambda r: (_order(r), r.rule, r.variant))
    return finding


def _order(r: Result) -> tuple[int, ...]:
    return tuple(-n for n in r.score)


def _read(session: Session, entity_id: int, on: date, netted: frozenset[str]) -> _Date | None:
    source = stored_source(session, entity_id, on, netted)
    if source is None:
        return None
    f = statements.figures(session, entity_id, source)
    by_id = fx.foreign_balances(session, entity_id, on)
    groups = {x.top for x in f.ledgers if x.key in source.revalued}
    return _Date(
        on=on,
        f=f,
        source=source,
        balances={x.key: by_id[x.id] for x in f.ledgers if x.id in by_id},
        book={x.key: x.balance for x in f.ledgers},
        tops={x.key: x.top for x in f.ledgers},
        groups=groups,
        theirs=_parts(source.lines, f, groups, taken_ok=False),
    )


def _values(rule: Rule, keys: set[str], d: _Date, rates: Rates) -> tuple[dict[str, Decimal], int]:
    """(each ledger's value under the rule, rounded to the paisa; ledger-dates without a
    rate, left at book value)."""
    found, missing = {}, 0
    for key in keys:
        value = _value(rule, key, d, rates)
        if value is None:
            missing += 1
            value = d.book.get(key, ZERO)
        found[key] = value.quantize(CENT)
    return found, missing


def _value(rule: Rule, key: str, d: _Date, rates: Rates) -> Decimal | None:
    """A ledger's value under the rule (unrounded); None without a rate."""
    if rule.rate is None:
        return d.book.get(key, ZERO)
    balance = d.balances.get(key)
    if balance is None or not balance.balance_fc:
        return ZERO  # nothing in a foreign currency: the source revalues it to 0
    rate = rule.rate(rates, balance.currency_name or "", d.on)
    return None if rate is None else balance.balance_fc * rate


def _per_ledger(result: LedgerResult, rule: Rule, d: _Date, rates: Rates) -> None:
    """Part 1: the rule's value against the source's own, for each foreign ledger."""
    for key in d.foreign:
        value = _value(rule, key, d, rates)
        if value is None:
            result.no_rate += 1
            continue
        theirs = d.source.revalued[key]
        result.compared += 1
        result.exact += abs(value.quantize(CENT) - theirs) < HALF_CENT
        result.rupee += abs(value.quantize(RUPEE) - theirs) < HALF_CENT
        result.near += abs(value - theirs) <= NEAR


def _tally(
    into: dict[tuple[str, str], Result],
    rule: str,
    ledgers: str,
    d: _Date,
    values: dict[str, Decimal],
    missing: int,
) -> None:
    """Lays the date out with these revalued values (the statements' own code for the
    groups) and counts the groups and each form of the forex line."""
    laid = replace(d.f, source=replace(d.source, revalued=values))
    ours_groups, _ = _parts([x for _, x in statements.lines_for(laid)], d.f, d.groups, True)
    groups_exact, groups_near = _equal(ours_groups, d.theirs[0])
    diffs = [(k, d.book[k] - v) for k, v in values.items() if k in d.book]
    first = True
    for form in FORMS:
        for sign, sign_label in SIGNS:
            variant = ", ".join(x for x in (ledgers, f"forex line {form}{sign_label}") if x)
            r = into.setdefault((rule, variant), Result(rule, variant))
            r.groups_exact += groups_exact
            r.groups_near += groups_near
            exact, near = _equal(_forex(form, sign, diffs, d), d.theirs[1])
            r.forex_exact += exact
            r.forex_near += near
            r.no_rate += missing if first else 0
            first = False


def _forex(form: str, sign: int, diffs: list[tuple[str, Decimal]], d: _Date) -> "Parts":
    """The forex line's parts (Trial Balance debit and credit, Balance Sheet amount) built
    from each ledger's book value less its revalued value, in one form."""
    if form == LEDGER_BY_LEDGER:
        units = [v for _, v in diffs]
    else:
        nets: dict[object, Decimal] = defaultdict(lambda: ZERO)
        for key, v in diffs:
            if form == "netted in total":
                unit: object = 0
            elif form == "netted per currency":
                balance = d.balances.get(key)
                unit = balance.currency_name if balance else ""
            else:
                unit = d.tops.get(key)
            nets[unit] += v
        units = list(nets.values())
    units = [sign * u for u in units]
    if not any(units):
        return {}
    key = statements.match_key(statements.UNADJUSTED_FOREX)
    debit = sum((u for u in units if u > 0), ZERO)
    credit = -sum((u for u in units if u < 0), ZERO)
    return {
        f"{TB}:{key}:debit": debit,
        f"{TB}:{key}:credit": credit,
        f"{BS}:{key}:amount": debit - credit,
    }


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


def _equal(ours: Parts, theirs: Parts) -> tuple[int, int]:
    """(1 if every part is equal to the paisa, 1 if every part is within 1)."""
    gaps = [abs(ours.get(k, ZERO) - theirs.get(k, ZERO)) for k in set(ours) | set(theirs)]
    return int(all(g < HALF_CENT for g in gaps)), int(all(g <= NEAR for g in gaps))
