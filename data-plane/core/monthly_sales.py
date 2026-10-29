"""Monthly sales, proven against the source (RPT-013). Source-independent; reads the
database only.

Where it fits: `./dev.ps1 statements` stores the source's own Profit and Loss at every month
end, for the books' beginning to that date (core/statements.py). Its Sales Accounts line is
therefore cumulative: the difference between two consecutive stored dates is the source's
own sales for exactly the days in between. `./dev.ps1 validate monthly-sales` compares each
such window with the sum of `ledgerbridge_reporting.v_daily_sales` over the same days
(migration 0021), from the books' beginning to the last stored date. `v_monthly_sales` is
those same days grouped by month, so every day of every month is proven. Where dates are
restricted (Educational mode, core/dates.py) a stored month end can be the 2nd of the next
month: the windows then aren't calendar months, but still cover every day once.

Signs: the stored lines are in the canonical sign (a credit is negative); the views show
sales positive, as an accountant reads them.

Before comparing, the check refuses when the stored statements are older than the
connection's latest sync or transform (the books changed since), and cross-checks the
Sales Accounts group: found by the source's own predefined group (renamed or not), with
ledgers mapped to sale of goods (standard account 4110) outside it reported, never silently
left out. Counts and dates only, never names or amounts.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from core import statements
from core.models import accounting as A  # noqa: N812
from core.models.reporting import StatementLine as LineRow
from core.models.system import SyncRun

ZERO = Decimal(0)
HALF_CENT = Decimal("0.005")
SALES_ROLE = "sales_accounts"  # the source's predefined Sales Accounts group
SALE_OF_GOODS = "4110"  # its standard account: the cross-check
# Runs that change the converted books (a deletion check only marks deletions: also counted).
DATA_RUNS = ("incremental", "full", "import", "deletion_check", "transform")

Daily = Callable[[Session, int], dict[date, Decimal]]


@dataclass(frozen=True)
class Window:
    """Days `start` to `end`, both included."""

    start: date
    end: date

    @property
    def exact_month(self) -> bool:
        return (
            self.start.day == 1
            and (self.end + timedelta(days=1)).day == 1
            and (self.start.month == self.end.month)
        )


def windows(books_from: date, dates: list[date]) -> list[Window]:
    """The windows between consecutive stored dates, the first from the books' beginning."""
    found, start = [], books_from
    for on in sorted(dates):
        if on < start:
            continue
        found.append(Window(start, on))
        start = on + timedelta(days=1)
    return found


@dataclass
class SalesGroup:
    """The entity's Sales Accounts group and what sits under it."""

    found: bool = False
    name: str = ""  # as the source's statements label it (never printed)
    sub_groups: int = 0
    ledgers: set[int] = field(default_factory=set)
    outside: int = 0  # ledgers mapped to sale of goods outside it, with entries
    with_opening: int = 0  # its ledgers with an opening balance


def sales_group(session: Session, entity_id: int) -> SalesGroup:
    """The Sales Accounts group by the source's own predefined group, its sub-groups at any
    depth and their ledgers; the cross-checks."""
    groups = session.execute(
        select(A.AccountGroup.id, A.AccountGroup.parent_id, A.AccountGroup.name,
               A.AccountGroup.predefined_role)
        .where(A.AccountGroup.entity_id == entity_id)
    ).all()  # fmt: skip
    top = next((g for g in groups if g.predefined_role == SALES_ROLE), None)
    found = SalesGroup()
    if top is not None:
        children: dict[int, list[int]] = defaultdict(list)
        for g in groups:
            if g.parent_id is not None:
                children[g.parent_id].append(g.id)
        tree, todo = {top.id}, [top.id]
        while todo:
            for child in children[todo.pop()]:
                if child not in tree:
                    tree.add(child)
                    todo.append(child)
        found = SalesGroup(True, top.name, len(tree) - 1)
        found.ledgers = set(
            session.scalars(
                select(A.Ledger.id).where(
                    A.Ledger.entity_id == entity_id, A.Ledger.group_id.in_(tree)
                )
            )
        )
        found.with_opening = (
            session.scalar(
                select(func.count()).where(
                    A.Ledger.id.in_(found.ledgers), A.Ledger.opening_balance != 0
                )
            )
            or 0
        )
    mapped = set(
        session.scalars(
            select(A.Ledger.id)
            .join(A.StandardAccount, A.StandardAccount.id == A.Ledger.standard_account_id)
            .where(A.Ledger.entity_id == entity_id, A.StandardAccount.code == SALE_OF_GOODS)
        )
    )
    posting = set(
        session.scalars(
            select(A.VoucherLine.ledger_id)
            .where(A.VoucherLine.ledger_id.in_(mapped - found.ledgers))
            .distinct()
        )
    ) if mapped - found.ledgers else set()  # fmt: skip
    found.outside = len(posting)
    return found


def daily_from_view(session: Session, entity_id: int) -> dict[date, Decimal]:
    """Net sales per day from `v_daily_sales` (what is proven)."""
    rows = session.execute(
        text(
            "SELECT on_date, SUM(net_sales) FROM ledgerbridge_reporting.v_daily_sales "
            "WHERE entity_id = :entity_id GROUP BY on_date"
        ),
        {"entity_id": entity_id},
    )
    return {_day(on): Decimal(str(net)) for on, net in rows}


def daily_from_books(session: Session, entity_id: int) -> dict[date, Decimal]:
    """Net sales per day computed here from the books, the same definition as the view:
    effective entries of vouchers not deleted on the Sales Accounts group's ledgers, sales
    positive. The reference the view is tested against."""
    ledgers = sales_group(session, entity_id).ledgers
    if not ledgers:
        return {}
    rows = session.execute(
        select(A.Voucher.voucher_date, func.sum(A.VoucherLine.amount))
        .join(A.Voucher, A.Voucher.id == A.VoucherLine.voucher_id)
        .where(
            A.Voucher.entity_id == entity_id,
            A.Voucher.is_deleted.is_(False),
            A.VoucherLine.is_effective.is_(True),
            A.VoucherLine.ledger_id.in_(ledgers),
        )
        .group_by(A.Voucher.voucher_date)
    )
    return {_day(on): -Decimal(str(total)) for on, total in rows}


def _day(value: object) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def stored_sales(session: Session, entity_id: int, label: str) -> dict[date, Decimal]:
    """The source's own Sales Accounts figure (canonical sign, cumulative from the books'
    beginning) at every date `statements` stored its Profit and Loss; 0 where it shows no
    such line."""
    key = statements.match_key(label)
    dates = session.scalars(
        select(LineRow.as_of)
        .where(
            LineRow.entity_id == entity_id,
            LineRow.figures == "source",
            LineRow.statement == "profit_loss",
        )
        .distinct()
    )
    found = {on: ZERO for on in dates}
    for on, level, amount in session.execute(
        select(LineRow.as_of, LineRow.level, LineRow.amount)
        .where(
            LineRow.entity_id == entity_id,
            LineRow.figures == "source",
            LineRow.statement == "profit_loss",
            LineRow.match_key == key,
        )
        .order_by(LineRow.line_no)
    ):
        if level == "main" or not found[on]:  # its main line where there is one
            found[on] = Decimal(amount)
    return found


@dataclass
class Stale:
    refreshed: datetime  # the oldest stored statement's refresh
    run_id: int
    run_type: str
    finished: datetime


def stale(session: Session, entity_id: int) -> Stale | None:
    """The latest sync or transform of the entity's connections that finished after the
    oldest stored source statement was refreshed; None when the statements are newer."""
    refreshed = session.scalar(
        select(func.min(LineRow.refreshed_at)).where(
            LineRow.entity_id == entity_id, LineRow.figures == "source"
        )
    )
    if refreshed is None:
        return None
    connections = select(A.EntitySource.connection_id).where(A.EntitySource.entity_id == entity_id)
    run = session.scalar(
        select(SyncRun)
        .where(
            SyncRun.connection_id.in_(connections),
            SyncRun.run_type.in_(DATA_RUNS),
            SyncRun.status == "succeeded",
            SyncRun.finished_at > refreshed,
        )
        .order_by(SyncRun.finished_at.desc())
        .limit(1)
    )
    if run is None:
        return None
    return Stale(refreshed, run.id, run.run_type, run.finished_at)


@dataclass
class Finding:
    group: SalesGroup
    stored_dates: int = 0
    first: date | None = None  # the books' beginning
    last: date | None = None  # the last stored date
    windows: int = 0
    exact_months: int = 0
    differing: list[Window] = field(default_factory=list)
    months_after: int = 0  # months with sales after the last stored date: not compared

    @property
    def matched(self) -> bool:
        return self.windows > 0 and not self.differing


def check(
    session: Session, entity_id: int, books_from: date, daily: Daily = daily_from_view
) -> Finding:
    """Every window between stored dates: ours (`daily`, by default the view) against the
    source's own Sales Accounts figure."""
    group = sales_group(session, entity_id)
    finding = Finding(group)
    if not group.found:
        return finding
    theirs = stored_sales(session, entity_id, group.name)
    if not theirs:
        return finding
    ours = daily(session, entity_id)
    finding.stored_dates = len(theirs)
    finding.first, finding.last = books_from, max(theirs)
    before = ZERO
    for w in windows(books_from, list(theirs)):
        source = -(theirs[w.end] - before)  # sales positive
        before = theirs[w.end]
        mine = sum((v for on, v in ours.items() if w.start <= on <= w.end), ZERO)
        finding.windows += 1
        finding.exact_months += w.exact_month
        if abs(mine - source) >= HALF_CENT:
            finding.differing.append(w)
    finding.months_after = len(
        {(on.year, on.month) for on, v in ours.items() if on > finding.last and v}
    )
    return finding
