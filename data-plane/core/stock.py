"""Stock for the dashboard (RPT-014): every stock item's quantities over a period and its
value, totals by stock group and godown, the stock value month by month, and one item's
movements voucher by voucher (the drill-down). Formulas F-STK-001 to F-STK-007 in
docs/formula-sheet.md.

- **Quantities are ours**, by the rule validation proves against the source item by item
  (VAL-006): the item's opening plus the stock movements of vouchers that aren't deleted,
  cancelled or optional and whose type moves stock, leaving out a job worker's location
  (`stock_moving`, used by both). A line moves `stock_quantity`: its quantity less any part a
  delivery or receipt note already moved.
- **Values are the source's own** (its valuation method), stored at its statement dates
  (`stock_values`, ADR-033): an item's, a stock group's, a godown's and the total. A period's
  value is the one at the **last stored date within it** (`value_on`), on which every
  selected company has its total stored.

An item is known by its **name** across the selected companies, as parties are: the same
item in two companies is one row, its figures added together.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, aliased

from core.models import accounting as A  # noqa: N812
from core.report_periods import Period, last_day

ZERO = Decimal(0)
LIMIT = 20_000  # movements on one item's page
RECENT = 12  # stored dates in the stock value chart


def counted_godown():  # noqa: ANN201 - a SQL condition
    """Inventory lines whose godown counts in stock balances: no godown, or one that isn't
    "our stock with a third party" (a job worker's location; ADR-031). Needs an outer join
    of `godowns` on the line's godown."""
    return or_(A.Godown.id.is_(None), A.Godown.holding != "ours_with_third_party")


def stock_moving(query, include_job_workers: bool = False):  # noqa: ANN001, ANN201
    """Limits a query on `inventory_lines` to the lines that move stock: vouchers not
    deleted, cancelled or optional, of a type that moves stock (orders and memorandum
    don't), not at a job worker's location (with `include_job_workers`, also there: the
    By-godown view shows that stock apart, core/stock_godowns.py)."""
    query = (
        query.join(A.Voucher, A.Voucher.id == A.InventoryLine.voucher_id)
        .join(A.VoucherType, A.VoucherType.id == A.Voucher.voucher_type_id)
        .outerjoin(A.Godown, A.Godown.id == A.InventoryLine.godown_id)
        .where(
            A.Voucher.is_deleted.is_(False),
            A.Voucher.is_cancelled.is_(False),
            A.Voucher.is_optional.is_(False),
            A.VoucherType.moves_stock.is_(True),
        )
    )
    return query if include_job_workers else query.where(counted_godown())


def _in_period(query, period: Period):  # noqa: ANN001, ANN202
    day = A.InventoryLine.voucher_date
    query = query.where(day >= period.start, day <= period.end)
    if period.months:  # only the chosen months
        months = [m.year * 100 + m.month for m in period.months]
        query = query.where((func.year(day) * 100 + func.month(day)).in_(months))
    return query


@dataclass
class ItemRow:
    item_id: int  # one of the items of that name (its page's id)
    name: str
    group: str | None
    unit: str | None
    companies: list[int]
    opening: Decimal = ZERO  # quantity at the period's start (F-STK-001)
    inward: Decimal = ZERO  # F-STK-002
    outward: Decimal = ZERO  # positive (F-STK-003)
    closing: Decimal = ZERO  # quantity at the period's end (F-STK-004)
    value: Decimal | None = None  # the source's, at `value_on` (F-STK-005)

    @property
    def rate(self) -> Decimal | None:
        """Value per unit at `value_on` (F-STK-006); None without a value or quantity."""
        if self.value is None or self.closing == 0:
            return None
        return (self.value / self.closing).quantize(Decimal("0.01"))


@dataclass
class StockSummary:
    value_on: date | None  # the last stored date within the period (values are at it)
    total_value: Decimal | None  # every item's together, the source's total
    items: list[ItemRow]
    by_group: list[tuple[str, Decimal]]  # top-level stock groups, the source's value
    by_godown: list[tuple[str, Decimal]]  # top-level godowns
    by_date: list[tuple[date, Decimal]] = field(default_factory=list)  # F-STK-007


@dataclass
class ItemRef:
    """An item known by name across the companies: their ids."""

    ids: list[int]
    name: str


@dataclass
class Movement:
    company: int
    on: date
    voucher_id: int
    voucher_number: str
    voucher_type: str
    godown: str | None
    other_godown: str | None  # where the stock went or came from (a move between godowns)
    quantity: Decimal  # signed: in +, out -
    balance: Decimal  # the quantity after it
    amount: Decimal  # the line's value on the voucher, signed like the quantity


@dataclass
class ItemMonth:
    month: date
    inward: Decimal
    outward: Decimal
    closing: Decimal
    value: Decimal | None  # the source's at the month's last stored date


@dataclass
class ItemPage:
    item: ItemRow
    value_on: date | None
    movements: list[Movement]
    truncated: bool
    months: list[ItemMonth]
    godown: str | None = None  # the movements and months are at this godown only
    by_godown: list = field(default_factory=list)  # GodownRow (core/stock_godowns.py)


# --- dates and values --------------------------------------------------------------------


def value_dates(session: Session, companies: list[int]) -> list[date]:
    """The dates every company has its source stock total stored for, earliest first."""
    rows = session.execute(
        select(A.StockValue.as_of, func.count(func.distinct(A.StockValue.entity_id)))
        .where(A.StockValue.entity_id.in_(companies), A.StockValue.scope == "total")
        .group_by(A.StockValue.as_of)
    ).all()
    return sorted(on for on, count in rows if count == len(set(companies)))


def _last_within(dates: list[date], end: date) -> date | None:
    return max((d for d in dates if d <= end), default=None)


def _values(session: Session, companies: list[int], on: date, scope: str) -> dict[str, Decimal]:
    """The source's closing value per name of a scope on a date, added up across companies."""
    found: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for name, value in session.execute(
        select(A.StockValue.scope_name, A.StockValue.closing_value).where(
            A.StockValue.entity_id.in_(companies),
            A.StockValue.as_of == on,
            A.StockValue.scope == scope,
        )
    ):
        found[name] += Decimal(value or 0)
    return dict(found)


def _top_level(session: Session, companies: list[int], model: type) -> set[str]:
    """Names of the stock groups (or godowns) at the top: their values hold the rest."""
    return set(
        session.scalars(
            select(model.name).where(
                model.entity_id.in_(companies),
                model.parent_id.is_(None),
                model.is_deleted.is_(False),
            )
        )
    )


def _by_name(values: dict[str, Decimal], names: set[str]) -> list[tuple[str, Decimal]]:
    found = [(name, value) for name, value in values.items() if name in names and value != 0]
    return sorted(found, key=lambda pair: (-abs(pair[1]), pair[0].lower()))


# --- quantities --------------------------------------------------------------------------


def _moved(companies: list[int], to: date | None = None, before: date | None = None):  # noqa: ANN202
    """Each item's stock movements, up to a date or before one."""
    query = stock_moving(
        select(A.InventoryLine.item_id, func.sum(A.InventoryLine.stock_quantity)).where(
            A.InventoryLine.entity_id.in_(companies)
        )
    )
    if to is not None:
        query = query.where(A.InventoryLine.voucher_date <= to)
    if before is not None:
        query = query.where(A.InventoryLine.voucher_date < before)
    return query.group_by(A.InventoryLine.item_id)


def _sums(session: Session, query) -> dict[int, Decimal]:  # noqa: ANN001
    return {int(item): Decimal(total or 0) for item, total in session.execute(query)}


def _rows(session: Session, companies: list[int], period: Period) -> tuple[list[ItemRow], dict]:
    """The items by name with their quantities; and each item id's row."""
    items = session.execute(
        select(A.Item.id, A.Item.entity_id, A.Item.name, A.ItemGroup.name, A.Unit.symbol,
               A.Item.opening_qty)
        .outerjoin(A.ItemGroup, A.ItemGroup.id == A.Item.item_group_id)
        .outerjoin(A.Unit, A.Unit.id == A.Item.unit_id)
        .where(A.Item.entity_id.in_(companies), A.Item.is_deleted.is_(False))
    ).all()  # fmt: skip
    before = _sums(session, _moved(companies, before=period.start))
    upto = _sums(session, _moved(companies, to=period.end))
    quantity = A.InventoryLine.stock_quantity
    within = _in_period(
        stock_moving(
            select(
                A.InventoryLine.item_id,
                func.sum(case((quantity > 0, quantity), else_=0)),
                func.sum(case((quantity < 0, -quantity), else_=0)),
            ).where(A.InventoryLine.entity_id.in_(companies))
        ),
        period,
    ).group_by(A.InventoryLine.item_id)
    moved = {int(i): (Decimal(a or 0), Decimal(b or 0)) for i, a, b in session.execute(within)}
    rows: dict[str, ItemRow] = {}
    by_id: dict[int, ItemRow] = {}
    for item_id, entity, name, group, unit, opening in items:
        row = rows.setdefault(name, ItemRow(item_id, name, group, unit, []))
        row.item_id = min(row.item_id, item_id)
        if entity not in row.companies:
            row.companies.append(entity)
        opening = Decimal(opening or 0)
        row.opening += opening + before.get(item_id, ZERO)
        row.closing += opening + upto.get(item_id, ZERO)
        inward, outward = moved.get(item_id, (ZERO, ZERO))
        row.inward += inward
        row.outward += outward
        by_id[item_id] = row
    return list(rows.values()), by_id


# --- the pages ---------------------------------------------------------------------------


def stock_summary(session: Session, companies: list[int], period: Period) -> StockSummary:
    """Every item with its quantities and value; values by stock group and godown; the stock
    value at the last stored dates. Items with a value first, the largest first."""
    items, _ = _rows(session, companies, period)
    dates = value_dates(session, companies)
    on = _last_within(dates, period.end)
    total = by_group = by_godown = None
    if on is not None:
        values = _values(session, companies, on, "item")
        for row in items:
            row.value = values.get(row.name) if values else None
        total = sum(_values(session, companies, on, "total").values(), ZERO)
        by_group = _by_name(
            _values(session, companies, on, "stock_group"),
            _top_level(session, companies, A.ItemGroup),
        )
        by_godown = _by_name(
            _values(session, companies, on, "godown"),
            _top_level(session, companies, A.Godown),
        )
    recent = [d for d in dates if d <= period.end][-RECENT:]
    by_date = [(d, sum(_values(session, companies, d, "total").values(), ZERO)) for d in recent]
    items.sort(key=lambda r: (r.value is None, -abs(r.value or ZERO), r.name.lower()))
    return StockSummary(on, total, items, by_group or [], by_godown or [], by_date)


def find_item(session: Session, companies: list[int], item_id: int) -> ItemRef | None:
    """The item and the others of its name in the companies; None outside them (or
    deleted)."""
    item = session.get(A.Item, item_id)
    if item is None or item.entity_id not in companies or item.is_deleted:
        return None
    ids = session.scalars(
        select(A.Item.id).where(
            A.Item.entity_id.in_(companies),
            A.Item.name == item.name,
            A.Item.is_deleted.is_(False),
        )
    ).all()
    return ItemRef(list(ids), item.name)


OTHER_GODOWN = aliased(A.Godown)


def _at_godown(query, godown: str | None):  # noqa: ANN001, ANN202
    """Limits the stock-moving lines to one godown, by name (a job worker's too)."""
    return query if godown is None else query.where(A.Godown.name == godown)


def _movements(
    session: Session,
    companies: list[int],
    ref: ItemRef,
    period: Period,
    opening: Decimal,
    godown: str | None = None,
) -> tuple[list[Movement], bool]:
    query = _in_period(
        _at_godown(
            stock_moving(
                select(A.InventoryLine.entity_id, A.InventoryLine.voucher_date, A.Voucher.id,
                       A.Voucher.voucher_number, A.VoucherType.name, A.Godown.name,
                       OTHER_GODOWN.name, A.InventoryLine.stock_quantity, A.InventoryLine.amount)
                .outerjoin(OTHER_GODOWN, OTHER_GODOWN.id == A.InventoryLine.counterpart_godown_id)
                .where(A.InventoryLine.entity_id.in_(companies),
                       A.InventoryLine.item_id.in_(ref.ids),
                       A.InventoryLine.stock_quantity != 0),
                include_job_workers=godown is not None,
            ),
            godown,
        ),
        period,
    ).order_by(A.InventoryLine.voucher_date, A.Voucher.id, A.InventoryLine.line_no)  # fmt: skip
    found: list[Movement] = []
    balance = opening
    for entity, on, vid, number, vtype, at, other, quantity, amount in session.execute(
        query.limit(LIMIT + 1)
    ):
        balance += Decimal(quantity)
        found.append(
            Movement(int(entity), on, int(vid), number, vtype, at, other, Decimal(quantity),
                     balance, Decimal(amount))
        )  # fmt: skip
    return found[:LIMIT], len(found) > LIMIT


def _months(
    session: Session,
    companies: list[int],
    ref: ItemRef,
    period: Period,
    opening_qty: Decimal,
    godown: str | None = None,
) -> list[ItemMonth]:
    """Each month of the period: in, out, the closing quantity and the source's value at
    the month's last stored date (at one godown: quantities only, as the source stores no
    value per item and godown)."""
    dates = value_dates(session, companies)
    months = []
    for month in period.month_starts():
        end = min(last_day(month), period.end)  # a period may end within its last month
        part = Period(month, end)
        quantity = A.InventoryLine.stock_quantity
        inward, outward = session.execute(
            _in_period(
                _at_godown(
                    stock_moving(
                        select(
                            func.sum(case((quantity > 0, quantity), else_=0)),
                            func.sum(case((quantity < 0, -quantity), else_=0)),
                        ).where(
                            A.InventoryLine.entity_id.in_(companies),
                            A.InventoryLine.item_id.in_(ref.ids),
                        ),
                        include_job_workers=godown is not None,
                    ),
                    godown,
                ),
                part,
            )
        ).one()
        if godown is None:
            moved = session.scalar(
                stock_moving(
                    select(func.sum(quantity)).where(
                        A.InventoryLine.entity_id.in_(companies),
                        A.InventoryLine.item_id.in_(ref.ids),
                        A.InventoryLine.voucher_date <= end,
                    )
                )
            )
            closing = opening_qty + Decimal(moved or 0)
            on = _last_within([d for d in dates if d >= month], end)
            value = _values(session, companies, on, "item").get(ref.name) if on else None
        else:
            closing, value = _at_godown_on(session, companies, ref, godown, end), None
        months.append(ItemMonth(month, Decimal(inward or 0), Decimal(outward or 0), closing, value))
    return months


def _at_godown_on(
    session: Session, companies: list[int], ref: ItemRef, godown: str, on: date
) -> Decimal:
    """The item's quantity at one godown at the end of a date (F-STK-010)."""
    from core.stock_godowns import quantities  # noqa: PLC0415 - it builds on this module

    found = quantities(session, companies, on, {ref.name})
    return sum((q for (_, _, at, _), q in found.items() if at == godown), ZERO)


def item_page(
    session: Session, companies: list[int], ref: ItemRef, period: Period, godown: str | None = None
) -> ItemPage:
    """The item's row, its movements in the period (the earliest first, with the quantity
    after each; at one godown when `godown` is given), its months, and where it is by
    godown and batch at the period's end."""
    from core.stock_godowns import by_godown  # noqa: PLC0415 - it builds on this module

    items, _ = _rows(session, companies, period)
    row = next(r for r in items if r.name == ref.name)
    summary_on = _last_within(value_dates(session, companies), period.end)
    if summary_on is not None:
        values = _values(session, companies, summary_on, "item")
        row.value = values.get(ref.name) if values else None
    opening_qty = sum(
        (Decimal(q or 0) for q in session.scalars(
            select(A.Item.opening_qty).where(A.Item.id.in_(ref.ids))
        )),
        ZERO,
    )  # fmt: skip
    start = row.opening
    if godown is not None:
        start = _at_godown_on(session, companies, ref, godown, period.start - timedelta(days=1))
    movements, truncated = _movements(session, companies, ref, period, start, godown)
    months = _months(session, companies, ref, period, opening_qty, godown)
    breakdown = by_godown(session, companies, period, {ref.name}).rows
    return ItemPage(row, summary_on, movements, truncated, months, godown, breakdown)
