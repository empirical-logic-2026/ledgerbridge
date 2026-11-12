"""The Balance Sheet's drill-down (ADR-055): a line's sub-groups and ledgers with their
balances at the Balance Sheet's date, down to each ledger (which opens its Ledger statement).
Formula F-BS-012 in docs/formula-sheet.md.

Built with the same figures as the stored Balance Sheet line (core/account_tree.py), so a
line's rows add up to it at every level:
- a ledger at its balance at the date (a foreign-currency ledger at the source's revalued
  balance stored for the date);
- the stock at its closing value, where the stock ledgers sit (else in the current assets
  group), as on the Balance Sheet;
- a group the stored Balance Sheet takes from the source (ADR-043): the gap it found,
  "Forex revaluation difference (per Tally, under review)", as a row inside it;
- Profit & Loss A/c: its two stored parts, the opening balance (the ledgers carrying earlier
  years' profit) and the current period's profit.

Amounts as the Balance Sheet shows them: assets as debits, liabilities and capital as
credits, both positive.
"""

from dataclasses import dataclass, field
from datetime import date
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
    stored_figures,
)
from core.models.reporting import StatementLine
from core.statements import COMPUTED, PROFIT_LOSS_ACCOUNT, REVALUATION_DIFFERENCE, TAKEN, match_key

SHEET_NATURES = ("equity", "liability", "asset")
PARTS = ("Opening Balance", "Current Period")  # Profit & Loss A/c's stored detail lines


@dataclass
class DrillRow:
    key: str
    label: str
    kind: str  # group, ledger, stock, line
    depth: int  # 0: the line itself
    parent: str | None
    amount: Decimal  # as the Balance Sheet shows it (F-BS-012)
    ledger_id: int | None = None
    company: int | None = None


@dataclass
class Drill:
    as_of: date | None
    line: str  # the line's label
    section: str
    rows: list[DrillRow] = field(default_factory=list)
    reason: str | None = None


def drill(session: Session, companies: list[int], as_of: date, key: str) -> Drill:
    """The rows under a Balance Sheet line ("assets:current assets") at a stored date."""
    section, _, name = key.partition(":")
    shown = 1 if section == "assets" else -1
    if match_key(name) == match_key(PROFIT_LOSS_ACCOUNT):
        return _profit_loss_account(session, companies, as_of, section, shown)
    tree = Tree()
    for entity_id in companies:
        f = stored_figures(session, entity_id, as_of)
        if f is None:
            return Drill(None, name, section, reason=f"no statement is stored for {as_of:%d-%b-%Y}")
        own = Tree()
        names = group_names(session, entity_id)
        natures = {g.id: g.nature for g in f.groups.values()}
        add_ledgers(
            own,
            f,
            entity_id,
            names,
            f.value,
            lambda x, natures=natures: natures.get(x.top) in SHEET_NATURES,
        )
        if f.replaces_stock and f.source.closing_stock is not None:
            add_stock(own, f, entity_id, names, "Closing stock", f.source.closing_stock)
        _taken(session, own, entity_id, as_of)
        tree.merge(own)
    root = tree.rows.get(f"g:/{match_key(name)}")
    if root is None:
        return Drill(as_of, name, section, reason="this line has no groups or ledgers to show")
    rows = [
        r for r in tree.ordered([root.key]) if r.key == root.key or _under(r.key, root.key, tree)
    ]
    return Drill(as_of, root.label, section, [_shown(r, shown) for r in rows])


def _under(key: str, root: str, tree: Tree) -> bool:
    row = tree.rows.get(key)
    while row is not None and row.parent is not None:
        if row.parent == root:
            return True
        row = tree.rows.get(row.parent)
    return False


def _shown(row: Row, sign: int) -> DrillRow:
    return DrillRow(
        row.key, row.label, row.kind, row.depth, row.parent, row.amount * sign,
        row.ledger_id, row.company,
    )  # fmt: skip


def _taken(session: Session, tree: Tree, entity_id: int, as_of: date) -> None:
    """ADR-043: the gap the stored Balance Sheet found for a group taken from the source,
    as a row inside it (amounts only: a Balance Sheet line is one figure)."""
    stored = dict(
        session.execute(
            select(StatementLine.label, StatementLine.amount).where(
                StatementLine.entity_id == entity_id,
                StatementLine.as_of == as_of,
                StatementLine.statement == "balance_sheet",
                StatementLine.figures == "ours",
            )
        ).all()
    )
    for label, amount in stored.items():
        if not label.endswith(TAKEN):
            continue
        name = label.removesuffix(TAKEN)
        computed = stored.get(name + COMPUTED)
        row = tree.rows.get(f"g:/{match_key(name)}")
        if computed is None or row is None:
            continue
        gap = amount - computed
        key = f"{row.key}/x:revaluation"
        tree.rows[key] = Row(
            key, REVALUATION_DIFFERENCE, "line", row.depth + 1, row.key, (3, 0, ""),
            fixed=(gap, ZERO) if gap > 0 else (ZERO, -gap),
        )  # fmt: skip
        total = row.amount + gap
        row.fixed = (total, ZERO) if total > 0 else (ZERO, -total)


def _profit_loss_account(
    session: Session, companies: list[int], as_of: date, section: str, shown: int
) -> Drill:
    """Profit & Loss A/c: its two stored parts, added up over the companies."""
    parts = {label: ZERO for label in PARTS}
    total = ZERO
    for label, level, amount in session.execute(
        select(StatementLine.label, StatementLine.level, StatementLine.amount).where(
            StatementLine.entity_id.in_(companies),
            StatementLine.as_of == as_of,
            StatementLine.statement == "balance_sheet",
            StatementLine.figures == "ours",
            StatementLine.label.in_((PROFIT_LOSS_ACCOUNT, *PARTS)),
        )
    ):
        if label == PROFIT_LOSS_ACCOUNT and level == "main":
            total += amount
        elif label in parts and level == "detail":
            parts[label] += amount
    root = DrillRow("g:/" + match_key(PROFIT_LOSS_ACCOUNT), PROFIT_LOSS_ACCOUNT, "group", 0,
                    None, total * shown)  # fmt: skip
    rows = [root] + [
        DrillRow(f"{root.key}/x:{match_key(label)}", label, "line", 1, root.key, amount * shown)
        for label, amount in parts.items()
    ]
    return Drill(as_of, PROFIT_LOSS_ACCOUNT, section, rows)
