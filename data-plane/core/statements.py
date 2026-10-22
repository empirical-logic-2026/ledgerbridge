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
- **Stock:** the opening and closing stock the source's Profit and Loss uses. Accounts
  integrated with inventory: the stock ledgers (`ledger_kind` stock) are left out and the
  stock appears at the opening value in the Trial Balance and at the closing value in the
  Balance Sheet. Not integrated: the stock ledgers are ordinary ledgers.
- **Foreign-currency ledgers:** at the balance the source reports (revalued at current
  rates); the difference to their book value is one "Unadjusted Forex Gain/Loss" line.
- **Ledgers directly under Primary** (the source's profit carriers, e.g. Tally's Profit &
  Loss A/c) belong to the Profit & Loss A/c line: their balance (Opening Balance) plus the
  period's profit (Current Period); on the liabilities side for a profit, the assets side
  for a loss.

Lines are one per primary group (the group's current name), plus the source's own lines
(Cost of Sales with Opening Stock, purchases and Closing Stock; Profit & Loss A/c;
Unadjusted Forex Gain/Loss). Our extra lines (Gross Profit, Net Profit, the two parts of
Profit & Loss A/c, a difference in opening balances) are `detail`, never compared.
"""

from collections import defaultdict
from dataclasses import dataclass, field
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
NATURE_ORDER = {"equity": 0, "liability": 1, "asset": 2, "income": 3, "expense": 4}
PROFIT_LOSS_ACCOUNT = "Profit & Loss A/c"
UNADJUSTED_FOREX = "Unadjusted Forex Gain/Loss"
OPENING_DIFFERENCE = "Difference in opening balances"


def match_key(label: str) -> str:
    """A line's label as both sides are compared: without the source's "Add: " / "Less: "
    and trailing ":", spaces collapsed, case folded."""
    text = " ".join(label.split()).casefold()
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
    balance: Decimal


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


@dataclass
class Comparison:
    as_of: date
    compared: int = 0
    differences: list[Difference] = field(default_factory=list)
    stock_before: tuple[Decimal | None, Decimal | None] | None = None  # stored before the read


# --- our books as of a date ---------------------------------------------------------------


def _books(session: Session, entity_id: int, as_of: date) -> tuple[list[_Ledger], dict[int, _Group]]:
    """Every ledger's balance as of the date (opening + effective lines), with the primary
    group it rolls up to; and the primary groups."""
    groups = {
        gid: (parent, name, nature, gross, code)
        for gid, parent, name, nature, gross, code in session.execute(
            select(
                A.AccountGroup.id,
                A.AccountGroup.parent_id,
                A.AccountGroup.name,
                A.AccountGroup.nature,
                A.AccountGroup.affects_gross_profit,
                A.StandardAccount.code,
            )
            .outerjoin(A.StandardAccount, A.StandardAccount.id == A.AccountGroup.standard_account_id)
            .where(A.AccountGroup.entity_id == entity_id, A.AccountGroup.is_deleted.is_(False))
        )
    }

    def top(gid: int) -> int:
        seen = set()
        while groups.get(gid, (None,))[0] is not None and gid not in seen:
            seen.add(gid)
            gid = groups[gid][0]
        return gid

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
        _Ledger(lid, key, name, top(gid), kind, Decimal(opening) + Decimal(moved))
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
        for gid, (_, name, nature, gross, code) in groups.items()
        if gid in tops
    }
    return ledgers, primary


# --- building ours ------------------------------------------------------------------------


@dataclass
class _Figures:
    """Our books and the source's figures for one date, sorted the way the statements need."""

    ledgers: list[_Ledger]
    groups: dict[int, _Group]
    source: SourceStatements

    @property
    def integrated(self) -> bool:
        return bool(self.source.integrated) and self.source.closing_stock is not None

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
            and not (self.integrated and ledger.kind == "stock")
        ]

    def stock_group(self) -> int | None:
        """The primary group the stock ledgers roll up to (e.g. Current Assets)."""
        return next((x.top for x in self.ledgers if x.kind == "stock"), None)

    def unadjusted(self) -> Decimal:
        return sum(
            (x.balance - self.source.revalued[x.key] for x in self.ledgers if x.key in self.source.revalued),
            ZERO,
        )

    def ordered_groups(self, natures: tuple[str, ...]) -> list[_Group]:
        found = [g for g in self.groups.values() if g.nature in natures]
        return sorted(found, key=lambda g: (NATURE_ORDER.get(g.nature or "", 9), g.id))


def build(session: Session, entity_id: int, source: SourceStatements) -> list[tuple[str | None, StatementLine]]:
    """Our three statements as of the source's date: (section, line) pairs."""
    ledgers, groups = _books(session, entity_id, source.as_of)
    figures = _Figures(ledgers, groups, source)
    profit_loss = _profit_loss(figures)
    net = sum((line.amount for _, line in profit_loss if line.level == "main"), ZERO)
    return [*_trial_balance(figures), *profit_loss, *_balance_sheet(figures, net)]


def _trial_balance(f: _Figures) -> list[tuple[str | None, StatementLine]]:
    by_group: dict[int, list[Decimal]] = defaultdict(list)
    for ledger in f.counted():
        by_group[ledger.top].append(f.value(ledger))
    if f.integrated and f.source.opening_stock is not None:
        stock = f.stock_group()
        if stock is not None:
            by_group[stock].append(f.source.opening_stock)  # the stock at its opening value
    lines = []
    for group in f.ordered_groups(tuple(NATURE_ORDER)):
        values = by_group.get(group.id, [])
        if values:
            lines.append(_tb_line(group.name, values))
    for ledger in f.ledgers:
        if ledger.key in f.source.profit_carriers and ledger.balance:
            lines.append(_tb_line(ledger.name, [ledger.balance]))
    unadjusted = f.unadjusted()
    if unadjusted:
        lines.append(_tb_line(UNADJUSTED_FOREX, [unadjusted]))
    total = sum((line.amount for line in lines), ZERO)
    if total:  # ours don't balance: the difference in opening balances, as a note
        lines.append(StatementLine("trial_balance", OPENING_DIFFERENCE, "detail", -total))
    return [(None, line) for line in lines]


def _tb_line(label: str, values: list[Decimal]) -> StatementLine:
    debit = sum((v for v in values if v > 0), ZERO)
    credit = -sum((v for v in values if v < 0), ZERO)
    return StatementLine("trial_balance", label, "main", debit - credit, debit, credit)


def _profit_loss(f: _Figures) -> list[tuple[str | None, StatementLine]]:
    totals: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for ledger in f.counted():
        totals[ledger.top] += f.value(ledger)
    groups = f.ordered_groups(("income", "expense"))
    gross = [g for g in groups if g.affects_gross_profit]
    purchases = [g for g in gross if g.standard_code == PURCHASES]
    has_stock = f.source.opening_stock is not None or f.source.closing_stock is not None
    lines: list[tuple[str | None, StatementLine]] = []

    def main(section: str, label: str, amount: Decimal) -> None:
        lines.append((section, StatementLine("profit_loss", label, "main", amount)))

    for group in gross:
        if group.nature == "income":
            main("gross", group.name, totals[group.id])
    if has_stock:
        opening = f.source.opening_stock or ZERO
        closing = f.source.closing_stock or ZERO
        bought = sum((totals[g.id] for g in purchases), ZERO)
        main("gross", "Cost of Sales :", opening + bought - closing)
        lines.append(("gross", StatementLine("profit_loss", "Opening Stock", "sub", opening)))
        for group in purchases:
            label = f"Add: {group.name}"
            lines.append(("gross", StatementLine("profit_loss", label, "sub", totals[group.id])))
        lines.append(("gross", StatementLine("profit_loss", "Less: Closing Stock", "sub", closing)))
    for group in gross:
        if group.nature == "expense" and (group not in purchases or not has_stock):
            main("gross", group.name, totals[group.id])
    gross_profit = sum((line.amount for _, line in lines if line.level == "main"), ZERO)
    lines.append(("gross", StatementLine("profit_loss", "Gross Profit", "detail", gross_profit)))
    for group in groups:
        if not group.affects_gross_profit:
            main("net", group.name, totals[group.id])
    net = sum((line.amount for _, line in lines if line.level == "main"), ZERO)
    lines.append(("net", StatementLine("profit_loss", "Net Profit", "detail", net)))
    return lines


def _balance_sheet(f: _Figures, net: Decimal) -> list[tuple[str | None, StatementLine]]:
    totals: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for ledger in f.counted():
        totals[ledger.top] += f.value(ledger)
    stock = f.stock_group()
    if f.integrated and stock is not None:
        totals[stock] += f.source.closing_stock or ZERO  # the stock at its closing value
    lines: list[tuple[str | None, StatementLine]] = []
    for group in f.ordered_groups(("equity", "liability", "asset")):
        section = "assets" if group.nature == "asset" else "liabilities"
        lines.append((section, StatementLine("balance_sheet", group.name, "main", totals[group.id])))
    carried = sum((x.balance for x in f.ledgers if x.key in f.source.profit_carriers), ZERO)
    account = carried + net
    side = _side(account)
    lines.append((side, StatementLine("balance_sheet", PROFIT_LOSS_ACCOUNT, "main", account)))
    lines.append((side, StatementLine("balance_sheet", "Opening Balance", "detail", carried)))
    lines.append((side, StatementLine("balance_sheet", "Current Period", "detail", net)))
    unadjusted = f.unadjusted()
    if unadjusted:
        lines.append(
            (_side(unadjusted), StatementLine("balance_sheet", UNADJUSTED_FOREX, "main", unadjusted))
        )
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
            for part in _parts(statement):
                x = (a[1][part] if a else ZERO)
                y = (b[1][part] if b else ZERO)
                compared += 1
                if abs(x - y) > tolerance:
                    differences.append(Difference(statement, f"{key}:{part}", label, x, y))
        for part in _parts(statement):
            x = sum((v[1][part] for v in mine.values()), ZERO)
            y = sum((v[1][part] for v in source.values()), ZERO)
            compared += 1
            if abs(x - y) > tolerance:
                differences.append(Difference(statement, f"total:{part}", "total", x, y))
    return compared, differences


def _parts(statement: str) -> tuple[str, ...]:
    return ("debit", "credit") if statement == "trial_balance" else ("amount",)


def _by_key(lines: list[StatementLine], statement: str) -> dict[str, tuple[str, dict[str, Decimal]]]:
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


def stored_stock(session: Session, entity_id: int, as_of: date) -> tuple[Decimal | None, Decimal | None] | None:
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
    ours = build(session, entity_id, source)
    _store_lines(session, entity_id, source.as_of, "source", [(_section(x), x) for x in source.lines], now)
    _store_lines(session, entity_id, source.as_of, "ours", ours, now)
    result.compared, result.differences = compare([x for _, x in ours], list(source.lines), tolerance)
    session.commit()
    return result


def _section(line: StatementLine) -> str | None:
    return _side(line.amount) if line.statement == "balance_sheet" else None


def _store_stock(session: Session, entity_id: int, connection_id: int, origin: str, source: SourceStatements, now: object) -> None:
    session.execute(
        delete(A.StockValue).where(A.StockValue.entity_id == entity_id, A.StockValue.as_of == source.as_of)
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


def _store_revaluations(session: Session, entity_id: int, connection_id: int, origin: str, source: SourceStatements, now: object) -> None:
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
