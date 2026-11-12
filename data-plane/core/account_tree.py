"""Groups, sub-groups and ledgers with their balances at a date, as the source's own reports
lay them out (ADR-055): the rows of the Trial Balance page and of the Balance Sheet's
drill-down. Source-independent: built from our books and the source's figures stored by the
statements refresh (core/statements.py), never read from the source on request.

- **The source's figures for a date** (`stored_source`): what `statements.refresh` stored for
  it (the source's statement lines, its stock values, foreign-currency ledgers at its
  revalued balance) and the reporting settings it read then (the groups netted for
  reporting, the ledgers carrying earlier years' profit; migration 0038). So a group's total
  here is the stored statement line's: the same `Figures` (core/statements.py) build both.
- **Debit and credit** (F-TB-001): a ledger is in the debit column when its balance is a
  debit, else in the credit column. A group splits ledger by ledger, a group the source nets
  for reporting counting as one figure (Tally's "Nett Debit/Credit Balances for Reporting").
- **Rows:** one per group with a balance, nested under its parent (`depth`), then its
  ledgers. Several companies: groups with the same names under the same parents are one
  row; a ledger is one row per company (the source's ledger report is per company).
"""

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.base import SourceStatements
from connectors.base import StatementLine as SourceLine
from core.models import accounting as A  # noqa: N812
from core.models.reporting import StatementLine
from core.statements import Figures, _books, _Ledger, match_key

ZERO = Decimal(0)
Unit = tuple[object, ...]  # what a figure splits into debit and credit by (company, kind, key)


def stored_source(session: Session, entity_id: int, as_of: date) -> SourceStatements | None:
    """The source's figures for a date, as the statements refresh stored them; None when no
    statement is stored for that date."""
    lines = tuple(
        SourceLine(statement, label, level, amount, debit, credit)
        for statement, label, level, amount, debit, credit in session.execute(
            select(
                StatementLine.statement, StatementLine.label, StatementLine.level,
                StatementLine.amount, StatementLine.debit, StatementLine.credit,
            )
            .where(
                StatementLine.entity_id == entity_id,
                StatementLine.as_of == as_of,
                StatementLine.figures == "source",
            )
            .order_by(StatementLine.line_no)
        )
    )  # fmt: skip
    stock = session.execute(
        select(
            A.StockValue.opening_value, A.StockValue.closing_value, A.StockValue.integrated
        ).where(
            A.StockValue.entity_id == entity_id,
            A.StockValue.as_of == as_of,
            A.StockValue.scope == "total",
        )
    ).first()
    if not lines and stock is None:
        return None
    revalued = dict(
        session.execute(
            select(A.Ledger.source_key, A.FxRevaluationSnapshot.revalued_value)
            .join(A.Ledger, A.Ledger.id == A.FxRevaluationSnapshot.ledger_id)
            .where(
                A.FxRevaluationSnapshot.entity_id == entity_id,
                A.FxRevaluationSnapshot.as_of == as_of,
            )
        ).all()
    )
    return SourceStatements(
        as_of=as_of,
        lines=lines,
        opening_stock=stock[0] if stock else None,
        closing_stock=stock[1] if stock else None,
        revalued=revalued,
        profit_carriers=_keys(session, A.Ledger, A.Ledger.carries_profit, entity_id),
        integrated=stock[2] if stock else None,
        netted_groups=_keys(session, A.AccountGroup, A.AccountGroup.nets_for_reporting, entity_id),
    )


def _keys(session: Session, model: type, flag: object, entity_id: int) -> frozenset[str]:
    return frozenset(
        session.scalars(
            select(model.source_key).where(  # type: ignore[attr-defined]
                model.entity_id == entity_id,  # type: ignore[attr-defined]
                flag.is_(True),  # type: ignore[attr-defined]
                model.is_deleted.is_(False),  # type: ignore[attr-defined]
            )
        )
    )


def settings_read(session: Session, entity_id: int) -> bool:
    """Whether the statements refresh has stored the reporting settings yet (migration
    0038): until then a netted group shows split, and earlier years' profit can't be found."""
    return (
        session.scalar(
            select(A.Ledger.id)
            .where(A.Ledger.entity_id == entity_id, A.Ledger.carries_profit.is_not(None))
            .limit(1)
        )
        is not None
    )


def stored_figures(session: Session, entity_id: int, as_of: date) -> Figures | None:
    """Our books at a date with the source's stored figures for it: the same `Figures` the
    stored statements were built from."""
    source = stored_source(session, entity_id, as_of)
    if source is None:
        return None
    ledgers, groups = _books(session, entity_id, as_of)
    return Figures(ledgers, groups, source)


# --- the rows ------------------------------------------------------------------------------


@dataclass
class Row:
    """A group, a ledger or a line of the source's own (stock, Profit & Loss A/c, forex,
    difference in opening balances)."""

    key: str  # "g:<names down the tree>", "l:<company>:<ledger id>", "x:<label>"
    label: str
    kind: str  # group, ledger, stock, line
    depth: int  # 0: a primary group or a line of its own
    parent: str | None
    order: tuple[object, ...] = ()
    units: dict[Unit, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))
    fixed: tuple[Decimal, Decimal] | None = None  # debit and credit given, not split
    ledger_id: int | None = None
    company: int | None = None

    @property
    def debit(self) -> Decimal:
        if self.fixed is not None:
            return self.fixed[0]
        return sum((v for v in self.units.values() if v > 0), ZERO)

    @property
    def credit(self) -> Decimal:
        if self.fixed is not None:
            return self.fixed[1]
        return -sum((v for v in self.units.values() if v < 0), ZERO)

    @property
    def amount(self) -> Decimal:
        """Debit less credit (F-TB-002): a debit balance positive."""
        return self.debit - self.credit


@dataclass
class _GroupInfo:
    name: str
    position: int | None


class Tree:
    """Rows built company by company; groups of the same names merge."""

    def __init__(self) -> None:
        self.rows: dict[str, Row] = {}

    def group_path(self, names: list[tuple[str, int | None]]) -> list[Row]:
        """The rows of a group and its parents, top first (created when new)."""
        found, key, parent = [], "g:", None
        for depth, (name, position) in enumerate(names):
            key = f"{key}/{match_key(name)}"
            row = self.rows.get(key)
            if row is None:
                row = Row(key, name, "group", depth, parent, (0, position or 0, name.casefold()))
                self.rows[key] = row
            found.append(row)
            parent = key
        return found

    def add(self, rows: Iterable[Row], unit: Unit, value: Decimal) -> None:
        for row in rows:
            row.units[unit] += value

    def leaf(self, parent: Row | None, row: Row, unit: Unit, value: Decimal) -> None:
        """A ledger or a stock row under its group."""
        row.parent = parent.key if parent else None
        row.depth = parent.depth + 1 if parent else 0
        existing = self.rows.setdefault(row.key, row)
        existing.units[unit] += value

    def merge(self, other: "Tree") -> None:
        """Another company's rows: the same groups add up (each company's figures keep their
        own split into debit and credit)."""
        for key, row in other.rows.items():
            mine = self.rows.get(key)
            if mine is None:
                self.rows[key] = row
            elif mine.fixed is not None or row.fixed is not None:
                mine.fixed = (mine.debit + row.debit, mine.credit + row.credit)
            else:
                for unit, amount in row.units.items():
                    mine.units[unit] += amount

    def ordered(self, top_order: list[str]) -> list[Row]:
        """Depth first: the primary groups (and lines) in `top_order`, each followed by its
        sub-groups (by the source's position, then name) and ledgers (by name)."""
        children: dict[str | None, list[Row]] = defaultdict(list)
        for row in self.rows.values():
            children[row.parent].append(row)
        rank = {key: n for n, key in enumerate(top_order)}
        result: list[Row] = []

        def walk(row: Row) -> None:
            result.append(row)
            for child in sorted(children[row.key], key=lambda r: r.order):
                walk(child)

        tops = sorted(children[None], key=lambda r: (rank.get(r.key, len(rank)), r.order))
        for top in tops:
            walk(top)
        return result


def group_names(session: Session, entity_id: int) -> dict[str, _GroupInfo]:
    """Every group's name and position by its source key."""
    return {
        key: _GroupInfo(name, position)
        for key, name, position in session.execute(
            select(
                A.AccountGroup.source_key, A.AccountGroup.name, A.AccountGroup.sort_position
            ).where(A.AccountGroup.entity_id == entity_id, A.AccountGroup.is_deleted.is_(False))
        )
    }


def add_ledgers(
    tree: Tree,
    f: Figures,
    entity_id: int,
    names: dict[str, _GroupInfo],
    value: Callable[[_Ledger], Decimal],
    keep: Callable[[_Ledger], bool] = lambda _: True,
) -> None:
    """Each counted ledger the source shows (`keep`) under its groups, with `value`."""
    for ledger in f.counted():
        if not keep(ledger):
            continue
        amount = value(ledger)
        path = tree.group_path(_path(ledger, names))
        unit = (entity_id, *f.unit(ledger))
        tree.add(path, unit, amount)
        row = Row(
            f"l:{entity_id}:{ledger.id}", ledger.name, "ledger", 0, None,
            (1, 0, ledger.name.casefold()), ledger_id=ledger.id, company=entity_id,
        )  # fmt: skip
        tree.leaf(path[-1] if path else None, row, (entity_id, "ledger", ledger.id), amount)


def add_stock(
    tree: Tree,
    f: Figures,
    entity_id: int,
    names: dict[str, _GroupInfo],
    label: str,
    amount: Decimal,
) -> None:
    """The source's stock value where the stock ledgers sit (else in the current assets
    group), as one row: the stock ledgers' groups get it in place of the ledgers."""
    stock_ledger = next((x for x in f.ledgers if x.kind == "stock"), None)
    if stock_ledger is not None:
        path = tree.group_path(_path(stock_ledger, names))
        unit: Unit = (entity_id, *f.unit(stock_ledger))
    else:
        group = f.stock_group()
        primary = f.groups.get(group) if group is not None else None
        path = tree.group_path([(primary.name, primary.sort_position)]) if primary else []
        unit = (entity_id, "stock", 0)
    tree.add(path, unit, amount)
    row = Row(f"x:stock:{entity_id}", label, "stock", 0, None, (2, 0, label), company=entity_id)
    tree.leaf(path[-1] if path else None, row, unit, amount)


def _path(ledger: _Ledger, names: dict[str, _GroupInfo]) -> list[tuple[str, int | None]]:
    """The ledger's groups, top first, as (name, position)."""
    found = []
    for key in reversed(ledger.groups):
        info = names.get(key)
        if info is not None:
            found.append((info.name, info.position))
    return found


def top_order(f: Figures, natures: tuple[str, ...]) -> list[str]:
    """The primary groups' row keys in the source's order."""
    return [f"g:/{match_key(g.name)}" for g in f.ordered_groups(natures)]
