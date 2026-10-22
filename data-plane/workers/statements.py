"""Refresh source-reported statement, stock and foreign-currency figures for an entity."""

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from connectors.base import STATEMENTS, SourceBalances, SourceStatements, StatementLine
from core.models import accounting as A  # noqa: N812
from core.models import reporting as R  # noqa: N812
from core.models.base import utcnow
from core.models.system import Connection
from core.names import normalise

_PREFIX = re.compile(r"^(?:add|less)\s*:\s*", re.IGNORECASE)
_TRAILING_PUNCTUATION = re.compile(r"[\s:]+$")
ZERO = Decimal(0)


@dataclass(frozen=True)
class StatementComparison:
    summary: list[str]
    private: list[str]


@dataclass(frozen=True)
class _Group:
    id: int
    parent_id: int | None
    name: str
    nature: str | None
    is_primary: bool
    affects_gross_profit: bool
    aliases: tuple[str, ...]


@dataclass
class _GroupTotals:
    amount: Decimal = ZERO
    debit: Decimal = ZERO
    credit: Decimal = ZERO


def _match_key(label: str) -> str:
    """Normalize display-only Add/Less prefixes and punctuation before matching a line."""
    return normalise(_TRAILING_PUNCTUATION.sub("", _PREFIX.sub("", label)))


def refresh_source_figures(
    session: Session,
    connection: Connection,
    entity_id: int,
    balances: SourceBalances,
) -> None:
    """Replace source snapshots for this date with the latest successful source read."""
    statements = balances.statements
    if statements is None:
        return

    as_of = balances.as_of
    read_at = utcnow()
    origin = str(connection.config.get("origin", "live"))
    _refresh_statement_lines(session, entity_id, as_of, statements, read_at)
    _refresh_stock_values(session, connection, entity_id, origin, statements, read_at)
    _refresh_revaluations(session, connection, entity_id, origin, balances, statements, read_at)
    _refresh_canonical_lines(session, entity_id, balances, read_at)


def _refresh_canonical_lines(
    session: Session,
    entity_id: int,
    balances: SourceBalances,
    refreshed_at: datetime,
) -> None:
    session.execute(
        delete(R.StatementLine).where(
            R.StatementLine.entity_id == entity_id,
            R.StatementLine.as_of == balances.as_of,
            R.StatementLine.figures == "ours",
        )
    )
    for statement, lines in build_canonical_statements(session, entity_id, balances).items():
        session.add_all(
            [
                R.StatementLine(
                    entity_id=entity_id,
                    as_of=balances.as_of,
                    statement=statement,
                    figures="ours",
                    line_no=line_no,
                    section=line.section,
                    label=line.label,
                    match_key=_match_key(line.label),
                    level=line.level,
                    amount=line.amount,
                    debit=line.debit,
                    credit=line.credit,
                    refreshed_at=refreshed_at,
                )
                for line_no, line in enumerate(lines)
            ]
        )


def build_canonical_statements(
    session: Session, entity_id: int, balances: SourceBalances
) -> dict[str, list[StatementLine]]:
    """Build canonical statements from ledger balances, group mappings and source valuation.

    Lines are grouped at the source group's primary level, but their amounts always come
    from our ledger records. In an integrated company, source stock-group values are added
    to their mapped asset group; the P&L stock controls come from the source P&L report.
    """
    groups = _groups(session, entity_id)
    primary_for = _primary_group_ids(groups)
    totals: dict[int, _GroupTotals] = defaultdict(_GroupTotals)
    ledger_rows = _ledger_balances(session, entity_id, balances.as_of)
    direct_ledgers: list[tuple[str, Decimal]] = []
    for source_key, name, group_id, balance in ledger_rows:
        if balances.integrated is True and source_key in balances.stock_ledgers:
            continue
        primary_id = primary_for.get(group_id)
        if primary_id is None:
            direct_ledgers.append((name, balance))
            continue
        group_totals = totals[primary_id]
        group_totals.amount += balance
        group_totals.debit += max(balance, ZERO)
        group_totals.credit += max(-balance, ZERO)

    if balances.integrated is True and balances.statements is not None:
        _add_integrated_stock(totals, groups, primary_for, balances.statements)

    trial_balance = [
        StatementLine(
            "trial_balance",
            group.name,
            "main",
            totals[group.id].amount,
            totals[group.id].debit,
            totals[group.id].credit,
        )
        for group in groups
        if group.is_primary
    ]
    trial_balance.extend(
        StatementLine("trial_balance", name, "main", amount, max(amount, ZERO), max(-amount, ZERO))
        for name, amount in direct_ledgers
    )

    balance_sheet = [
        StatementLine("balance_sheet", group.name, "main", totals[group.id].amount)
        for group in groups
        if group.is_primary and group.nature in ("asset", "liability", "equity")
    ]
    profit_loss = _profit_and_loss(groups, totals, balances)
    profit = sum((line.amount for line in profit_loss if line.level == "main"), ZERO)
    if balances.statements is not None:
        for key in sorted(balances.profit_carriers):
            ledger = session.scalar(
                select(A.Ledger.name).where(
                    A.Ledger.entity_id == entity_id,
                    A.Ledger.source_key == key,
                    A.Ledger.is_deleted.is_(False),
                )
            )
            if ledger is not None:
                trial_balance.append(
                    StatementLine(
                        "trial_balance",
                        ledger,
                        "main",
                        profit,
                        max(profit, ZERO),
                        max(-profit, ZERO),
                    )
                )
                balance_sheet.append(StatementLine("balance_sheet", ledger, "main", profit))

    return {
        "trial_balance": trial_balance,
        "profit_loss": profit_loss,
        "balance_sheet": balance_sheet,
    }


def _groups(session: Session, entity_id: int) -> list[_Group]:
    return [
        _Group(
            id=group.id,
            parent_id=group.parent_id,
            name=group.name,
            nature=group.nature,
            is_primary=group.is_primary,
            affects_gross_profit=group.affects_gross_profit,
            aliases=tuple((group.extra or {}).get("_aliases", ())),
        )
        for group in session.scalars(
            select(A.AccountGroup)
            .where(
                A.AccountGroup.entity_id == entity_id,
                A.AccountGroup.is_deleted.is_(False),
            )
            .order_by(A.AccountGroup.name)
        )
    ]


def _primary_group_ids(groups: Iterable[_Group]) -> dict[int, int]:
    by_id = {group.id: group for group in groups}
    roots = {}
    for group in by_id.values():
        current = group
        visited = set()
        while not current.is_primary and current.parent_id in by_id:
            if current.id in visited:
                break
            visited.add(current.id)
            current = by_id[current.parent_id]
        if current.is_primary:
            roots[group.id] = current.id
    return roots


def _ledger_balances(
    session: Session, entity_id: int, as_of: date
) -> list[tuple[str, str, int, Decimal]]:
    movements = (
        select(A.VoucherLine.ledger_id, func.sum(A.VoucherLine.amount).label("movement"))
        .where(
            A.VoucherLine.entity_id == entity_id,
            A.VoucherLine.is_effective.is_(True),
            A.VoucherLine.voucher_date <= as_of,
        )
        .group_by(A.VoucherLine.ledger_id)
        .subquery()
    )
    return [
        (source_key, name, group_id, Decimal(opening) + Decimal(movement or 0))
        for source_key, name, group_id, opening, movement in session.execute(
            select(
                A.Ledger.source_key,
                A.Ledger.name,
                A.Ledger.group_id,
                A.Ledger.opening_balance,
                movements.c.movement,
            )
            .outerjoin(movements, movements.c.ledger_id == A.Ledger.id)
            .where(
                A.Ledger.entity_id == entity_id,
                A.Ledger.is_deleted.is_(False),
            )
        )
    ]


def _add_integrated_stock(
    totals: dict[int, _GroupTotals],
    groups: list[_Group],
    primary_for: Mapping[int, int],
    statements: SourceStatements,
) -> None:
    """Include integrated stock in the primary asset group without counting parent totals twice."""
    stock_groups = {
        normalise(value.name): value
        for value in statements.stock
        if value.scope == "stock_group" and value.closing is not None
    }
    stock_group_names = set(stock_groups)
    group_by_id = {group.id: group for group in groups}
    children: dict[int, set[int]] = defaultdict(set)
    for group in groups:
        if group.parent_id is not None:
            children[group.parent_id].add(group.id)
    for name, value in stock_groups.items():
        matches = [
            group
            for group in groups
            if name in {normalise(group.name), *(normalise(alias) for alias in group.aliases)}
        ]
        if len(matches) != 1:
            continue
        group = matches[0]
        descendants = set()
        pending = list(children.get(group.id, ()))
        while pending:
            child_id = pending.pop()
            descendants.add(child_id)
            pending.extend(children.get(child_id, ()))
        if any(
            normalise(child.name) in stock_group_names
            or any(normalise(alias) in stock_group_names for alias in child.aliases)
            for child in (group_by_id[child_id] for child_id in descendants)
        ):
            continue
        primary_id = primary_for.get(group.id)
        if primary_id is not None:
            total = totals[primary_id]
            total.amount += value.closing or ZERO
            total.debit += max(value.closing or ZERO, ZERO)
            total.credit += max(-(value.closing or ZERO), ZERO)


def _profit_and_loss(
    groups: list[_Group],
    totals: Mapping[int, _GroupTotals],
    balances: SourceBalances,
) -> list[StatementLine]:
    profit_groups = [
        group for group in groups if group.is_primary and group.nature in ("income", "expense")
    ]
    cost_groups = [group for group in profit_groups if group.affects_gross_profit]
    other_groups = [group for group in profit_groups if not group.affects_gross_profit]
    lines = [
        StatementLine("profit_loss", group.name, "main", totals[group.id].amount)
        for group in other_groups
    ]
    opening = balances.opening_stock
    closing = balances.closing_stock
    if cost_groups or opening is not None or closing is not None:
        cost = sum((totals[group.id].amount for group in cost_groups), ZERO)
        cost += opening or ZERO
        cost -= closing or ZERO
        lines.append(StatementLine("profit_loss", "Cost of Sales", "main", cost))
        if opening is not None:
            lines.append(
                StatementLine(
                    "profit_loss", "Opening Stock", "sub", opening, section="Cost of Sales"
                )
            )
        for group in cost_groups:
            lines.append(
                StatementLine(
                    "profit_loss",
                    f"Add: {group.name}",
                    "sub",
                    totals[group.id].amount,
                    section="Cost of Sales",
                )
            )
        if closing is not None:
            lines.append(
                StatementLine(
                    "profit_loss",
                    "Less: Closing Stock",
                    "sub",
                    closing,
                    section="Cost of Sales",
                )
            )
    return lines


def compare_statement_lines(
    session: Session,
    entity_id: int,
    as_of: date,
    tolerance: Decimal,
) -> StatementComparison:
    """Compare persisted canonical and source lines without printing their labels or amounts."""
    summary = []
    private = []
    for statement in STATEMENTS:
        rows = list(
            session.execute(
                select(
                    R.StatementLine.figures,
                    R.StatementLine.label,
                    R.StatementLine.match_key,
                    R.StatementLine.level,
                    R.StatementLine.amount,
                ).where(
                    R.StatementLine.entity_id == entity_id,
                    R.StatementLine.as_of == as_of,
                    R.StatementLine.statement == statement,
                    R.StatementLine.level != "detail",
                )
            )
        )
        ours = _statement_totals(rows, "ours")
        source = _statement_totals(rows, "source")
        keys = sorted(set(ours) | set(source))
        equal = different = ours_only = source_only = 0
        for key in keys:
            our_amount = ours.get(key)
            source_amount = source.get(key)
            label = (ours.get(key) or source[key])[0]
            if our_amount is None:
                source_only += 1
                status = "source-only"
                difference = None
            elif source_amount is None:
                ours_only += 1
                status = "ours-only"
                difference = None
            else:
                difference = our_amount[1] - source_amount[1]
                if abs(difference) <= tolerance:
                    equal += 1
                    status = "equal"
                else:
                    different += 1
                    status = "different"
            private.append(
                "\t".join(
                    (
                        statement,
                        _safe(label),
                        "" if our_amount is None else str(our_amount[1]),
                        "" if source_amount is None else str(source_amount[1]),
                        "" if difference is None else str(difference),
                        status,
                    )
                )
            )
        summary.append(
            f"{statement}: canonical {len(ours)}, source {len(source)}, "
            f"matched {len(keys) - ours_only - source_only}, equal {equal}, "
            f"different {different}, canonical-only {ours_only}, source-only {source_only}"
        )
    return StatementComparison(summary, private)


def _statement_totals(
    rows: Iterable[tuple[str, str, str, str, Decimal]], figures: str
) -> dict[tuple[str, str], tuple[str, Decimal]]:
    totals: dict[tuple[str, str], tuple[str, Decimal]] = {}
    for row_figures, label, match_key, level, amount in rows:
        if row_figures != figures:
            continue
        key = match_key, level
        previous = totals.get(key)
        totals[key] = (label, Decimal(amount) + (previous[1] if previous else ZERO))
    return totals


def _safe(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _refresh_statement_lines(
    session: Session,
    entity_id: int,
    as_of: date,
    statements: SourceStatements,
    refreshed_at: datetime,
) -> None:
    session.execute(
        delete(R.StatementLine).where(
            R.StatementLine.entity_id == entity_id,
            R.StatementLine.as_of == as_of,
            R.StatementLine.figures == "source",
        )
    )
    session.add_all(
        [
            R.StatementLine(
                entity_id=entity_id,
                as_of=as_of,
                statement=line.statement,
                figures="source",
                line_no=line_no,
                section=line.section,
                label=line.label,
                match_key=_match_key(line.label),
                level=line.level,
                amount=line.amount,
                debit=line.debit,
                credit=line.credit,
                refreshed_at=refreshed_at,
            )
            for line_no, line in enumerate(statements.lines)
        ]
    )


def _refresh_stock_values(
    session: Session,
    connection: Connection,
    entity_id: int,
    origin: str,
    statements: SourceStatements,
    read_at: datetime,
) -> None:
    session.execute(
        delete(A.StockValue).where(
            A.StockValue.entity_id == entity_id,
            A.StockValue.as_of == statements.as_of,
        )
    )
    session.add_all(
        [
            A.StockValue(
                entity_id=entity_id,
                connection_id=connection.id,
                origin=origin,
                as_of=statements.as_of,
                scope=value.scope,
                scope_name=value.name,
                opening_value=value.opening,
                closing_value=value.closing,
                integrated=(statements.integrated if value.scope == "total" else None),
                read_at=read_at,
            )
            for value in statements.stock
        ]
    )


def _refresh_revaluations(
    session: Session,
    connection: Connection,
    entity_id: int,
    origin: str,
    balances: SourceBalances,
    statements: SourceStatements,
    read_at: datetime,
) -> None:
    session.execute(
        delete(A.FxRevaluationSnapshot).where(
            A.FxRevaluationSnapshot.entity_id == entity_id,
            A.FxRevaluationSnapshot.as_of == statements.as_of,
        )
    )
    book_values = {key: value for keys, value in balances.book_values.items() for key in keys}
    for source_key in sorted(balances.foreign_ledgers):
        ledger = session.scalar(
            select(A.Ledger).where(
                A.Ledger.entity_id == entity_id,
                A.Ledger.source_key == source_key,
                A.Ledger.is_deleted.is_(False),
            )
        )
        book_value = book_values.get(source_key)
        revalued_value = statements.revalued.get(source_key)
        if ledger is None or book_value is None or revalued_value is None:
            continue
        session.add(
            A.FxRevaluationSnapshot(
                entity_id=entity_id,
                ledger_id=ledger.id,
                connection_id=connection.id,
                origin=origin,
                as_of=statements.as_of,
                currency_code=ledger.currency_code,
                balance_fc=None,
                book_value=book_value,
                revalued_value=revalued_value,
                unrealised_gain_loss=book_value - revalued_value,
                read_at=read_at,
            )
        )
