"""Cost centres for the dashboard (RPT-014): each cost centre's allocations by month, and one
cost centre's allocations voucher by voucher (the drill-down). Source-independent: read from
`v_cost_allocations` (one row per allocation of an effective line of a voucher not deleted,
migration 0026). Amounts use the canonical sign (debit positive, as the line's).

A cost centre is known by its **name and category** across the selected companies (as
parties are by name): the same cost centre in two companies is one row, its figures added
together. Its own allocations only; the cost centres under it have their own rows (`parent`
says where each sits). Formula F-CC-001 in docs/formula-sheet.md.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from core.models import accounting as A  # noqa: N812
from core.report_periods import Period
from core.reporting_views import COST_ALLOCATIONS as CA

ZERO = Decimal(0)
LIMIT = 20_000  # allocations on one cost centre's page


@dataclass
class CentreRow:
    centre_id: int  # one of the cost centres of that name and category (its page's id)
    name: str
    category: str | None
    parent: str | None
    companies: list[int]
    months: dict[date, Decimal] = field(default_factory=dict)
    total: Decimal = ZERO
    allocations: int = 0


@dataclass
class Allocation:
    company: int
    on: date
    voucher_id: int
    voucher_number: str
    voucher_type: str
    ledger: str
    category: str | None
    amount: Decimal


@dataclass
class CentreRef:
    """A cost centre known by name and category across the companies: their ids."""

    ids: list[int]
    name: str
    category: str | None


@dataclass
class CentrePage:
    centre: CentreRow
    allocations: list[Allocation]
    truncated: bool


def _in_period(query, period: Period):  # noqa: ANN001, ANN202
    """`in_period` on the view's own date column."""
    day = CA.c.voucher_date
    query = query.where(day >= period.start, day <= period.end)
    if period.months:
        months = [m.year * 100 + m.month for m in period.months]
        query = query.where((func.year(day) * 100 + func.month(day)).in_(months))
    return query


def cost_centres(session: Session, companies: list[int], period: Period) -> list[CentreRow]:
    """Every cost centre of the companies (not deleted), with its allocations by month; the
    largest total first, then by name."""
    parent = aliased(A.CostCentre)
    category = aliased(A.CostCategory)
    centres = session.execute(
        select(A.CostCentre.id, A.CostCentre.entity_id, A.CostCentre.name,
               func.coalesce(category.name, A.CostCentre.category), parent.name)
        .outerjoin(category, category.id == A.CostCentre.cost_category_id)
        .outerjoin(parent, parent.id == A.CostCentre.parent_id)
        .where(A.CostCentre.entity_id.in_(companies), A.CostCentre.is_deleted.is_(False))
    ).all()  # fmt: skip
    rows: dict[tuple[str, str | None], CentreRow] = {}
    by_id: dict[int, CentreRow] = {}
    for cid, entity, name, cat, parent_name in centres:
        row = rows.setdefault((name, cat), CentreRow(cid, name, cat, parent_name, []))
        row.centre_id = min(row.centre_id, cid)
        if entity not in row.companies:
            row.companies.append(entity)
        by_id[cid] = row
    year, month = func.year(CA.c.voucher_date), func.month(CA.c.voucher_date)
    query = _in_period(
        select(CA.c.cost_centre_id, year, month, func.sum(CA.c.amount), func.count())
        .where(CA.c.entity_id.in_(companies))
        .group_by(CA.c.cost_centre_id, year, month),
        period,
    )
    for cid, y, m, amount, count in session.execute(query):
        row = by_id.get(int(cid))
        if row is None:
            continue
        key = date(int(y), int(m), 1)
        row.months[key] = row.months.get(key, ZERO) + Decimal(amount)
        row.total += Decimal(amount)
        row.allocations += int(count)
    return sorted(rows.values(), key=lambda r: (-abs(r.total), r.name.lower()))


def find_centre(session: Session, companies: list[int], centre_id: int) -> CentreRef | None:
    """The cost centre and the others of its name and category in the companies; None
    outside them (or deleted)."""
    centre = session.get(A.CostCentre, centre_id)
    if centre is None or centre.entity_id not in companies or centre.is_deleted:
        return None
    category = _category_name(session, centre)
    same = session.scalars(
        select(A.CostCentre).where(
            A.CostCentre.entity_id.in_(companies),
            A.CostCentre.name == centre.name,
            A.CostCentre.is_deleted.is_(False),
        )
    ).all()
    ids = [c.id for c in same if _category_name(session, c) == category]
    return CentreRef(ids, centre.name, category)


def _category_name(session: Session, centre: A.CostCentre) -> str | None:
    if centre.cost_category_id is not None:
        return session.get_one(A.CostCategory, centre.cost_category_id).name
    return centre.category


def centre_page(
    session: Session, companies: list[int], ref: CentreRef, period: Period
) -> CentrePage:
    """The cost centre's row and its allocations in the period, the earliest first."""
    rows = cost_centres(session, companies, period)
    centre = next(r for r in rows if (r.name, r.category) == (ref.name, ref.category))
    query = _in_period(
        select(CA.c.entity_id, CA.c.voucher_date, CA.c.voucher_id, CA.c.voucher_number,
               CA.c.voucher_type, CA.c.ledger, CA.c.cost_category, CA.c.amount)
        .where(CA.c.entity_id.in_(companies), CA.c.cost_centre_id.in_(ref.ids))
        .order_by(CA.c.voucher_date, CA.c.voucher_id)
        .limit(LIMIT + 1),
        period,
    )  # fmt: skip
    found = [
        Allocation(int(e), on, int(vid), number, vtype, ledger, category, Decimal(amount))
        for e, on, vid, number, vtype, ledger, category, amount in session.execute(query)
    ]
    return CentrePage(centre, found[:LIMIT], len(found) > LIMIT)


def totals_by_month(rows: list[CentreRow]) -> dict[date, Decimal]:
    """All cost centres' allocations by month (the page's total row)."""
    months: dict[date, Decimal] = defaultdict(lambda: ZERO)
    for row in rows:
        for month, amount in row.months.items():
            months[month] += amount
    return dict(months)
