"""Stock by godown and batch at a date (the Stock page's "By godown" view and the item page's
breakdown; formulas F-STK-010 to F-STK-013 in docs/formula-sheet.md).

A row is one item (by name across the companies), godown and batch, with its quantity at the
date: the openings by godown and batch (`item_opening_batches`), plus the stock-moving
inventory lines up to the date at that godown and batch. An item's opening that isn't split
by godown is a row without a godown, so nothing is lost.

Three sections, by whose stock the godown holds (`godowns.holding`, ADR-031), counted as
Tally counts them (proved on the test company's recordings, tests/test_stock_godowns.py):

- **ours** (`own`): our stock in our godowns. In the total.
- **held_for_others** (`third_party_with_us`): others' stock held with us. Not ours, but
  Tally's Stock Summary and closing stock include it, so it is in the total too.
- **at_job_workers** (`ours_with_third_party`): our stock at a job worker. Tally leaves it
  out of its Stock Summary, its closing stock and the item balances (it records there only
  what the job worker consumed), so it is outside the total.

So the total of `ours` and `held_for_others` equals each item's closing quantity on the
Stock page (core/stock.py) and Tally's Stock Summary. A row's value is its quantity times the
item's rate (F-STK-006, the source's value at the last stored date within the period); the
item's last counted row takes the rounding remainder, so an item's rows add up exactly to
its stored value. Rows at a job worker have no value: Tally values none there.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import accounting as A  # noqa: N812
from core.report_periods import Period
from core.stock import _last_within, _rows, _values, stock_moving, value_dates

ZERO = Decimal(0)
CENT = Decimal("0.01")
SECTIONS = ("ours", "held_for_others", "at_job_workers")
SECTION_OF = {
    "own": "ours",
    "third_party_with_us": "held_for_others",
    "ours_with_third_party": "at_job_workers",
}
IN_TOTAL = ("ours", "held_for_others")  # as Tally's Stock Summary counts


@dataclass
class GodownRow:
    section: str  # ours, held_for_others, at_job_workers
    item_id: int  # one of the items of that name (its page's id)
    item: str
    unit: str | None
    godown: str | None  # None: an opening not split by godown
    batch: str | None
    quantity: Decimal = ZERO  # at the date (F-STK-010)
    value: Decimal | None = None  # quantity x the item's rate (F-STK-011); None at job workers


@dataclass
class ByGodown:
    on: date  # the quantities are at this date (the period's end)
    value_on: date | None  # the values are the source's at this date
    rows: list[GodownRow]
    godown_values: dict[str, Decimal] = field(default_factory=dict)  # the source's own, by name

    def total(self, section: str) -> tuple[Decimal, Decimal | None]:
        """A section's quantity and value (None when no row of it has a value)."""
        rows = [r for r in self.rows if r.section == section]
        values = [r.value for r in rows if r.value is not None]
        return sum((r.quantity for r in rows), ZERO), (sum(values, ZERO) if values else None)

    def counted(self) -> tuple[Decimal, Decimal | None]:
        """The total that equals the Stock page and Tally's Stock Summary (F-STK-010)."""
        parts = [self.total(s) for s in IN_TOTAL]
        values = [v for _, v in parts if v is not None]
        return sum((q for q, _ in parts), ZERO), (sum(values, ZERO) if values else None)


def _items(session: Session, companies: list[int], names: set[str] | None) -> dict[int, tuple]:
    """Item id -> (name, unit, opening quantity)."""
    query = (
        select(A.Item.id, A.Item.name, A.Unit.symbol, A.Item.opening_qty)
        .outerjoin(A.Unit, A.Unit.id == A.Item.unit_id)
        .where(A.Item.entity_id.in_(companies), A.Item.is_deleted.is_(False))
    )
    if names is not None:
        query = query.where(A.Item.name.in_(names))
    return {int(i): (n, u, Decimal(q or 0)) for i, n, u, q in session.execute(query)}


def _godowns(session: Session, companies: list[int]) -> dict[int, tuple[str, str]]:
    """Godown id -> (name, section)."""
    rows = session.execute(
        select(A.Godown.id, A.Godown.name, A.Godown.holding).where(
            A.Godown.entity_id.in_(companies)
        )
    )
    return {int(g): (name, SECTION_OF.get(holding, "ours")) for g, name, holding in rows}


def quantities(
    session: Session, companies: list[int], on: date, names: set[str] | None = None
) -> dict[tuple[str, str, str | None, str | None], Decimal]:
    """(section, item name, godown name, batch) -> quantity at the end of `on` (F-STK-010);
    only the items named, when `names` is given."""
    items = _items(session, companies, names)
    godowns = _godowns(session, companies)
    found: dict[tuple, Decimal] = defaultdict(lambda: ZERO)

    def add(item_id: int, godown_id: int | None, batch: str | None, quantity: Decimal) -> None:
        name = items[item_id][0]
        godown, section = godowns.get(godown_id, (None, "ours")) if godown_id else (None, "ours")
        found[(section, name, godown, batch or None)] += quantity

    # The openings by godown and batch; what isn't split by godown stays without one.
    split: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for item_id, godown_id, batch, quantity in session.execute(
        select(A.ItemOpeningBatch.item_id, A.ItemOpeningBatch.godown_id,
               A.ItemOpeningBatch.batch_name, A.ItemOpeningBatch.quantity)
        .where(A.ItemOpeningBatch.item_id.in_(list(items)))
    ):  # fmt: skip
        add(int(item_id), godown_id, batch, Decimal(quantity))
        section = godowns.get(godown_id, (None, "ours"))[1] if godown_id else "ours"
        if section != "at_job_workers":  # the item's opening is what Tally counts
            split[int(item_id)] += Decimal(quantity)
    for item_id, (_, _, opening) in items.items():
        if opening - split[item_id] != 0:
            add(item_id, None, None, opening - split[item_id])
    # The movements up to the date, at every godown (job workers' too).
    moved = stock_moving(
        select(
            A.InventoryLine.item_id,
            A.InventoryLine.godown_id,
            A.InventoryLine.batch_name,
            func.sum(A.InventoryLine.stock_quantity),
        ).where(
            A.InventoryLine.entity_id.in_(companies),
            A.InventoryLine.item_id.in_(list(items)),
            A.InventoryLine.voucher_date <= on,
        ),
        include_job_workers=True,
    )
    moved = moved.group_by(
        A.InventoryLine.item_id, A.InventoryLine.godown_id, A.InventoryLine.batch_name
    )
    for item_id, godown_id, batch, quantity in session.execute(moved):
        add(int(item_id), godown_id, batch, Decimal(quantity or 0))
    return {key: q for key, q in found.items() if q != 0}


def _allocate(rows: list[GodownRow], value: Decimal | None, closing: Decimal) -> None:
    """Values the item's counted rows at its rate; the last takes the rounding remainder,
    so they add up to `value` exactly (F-STK-011)."""
    counted = [r for r in rows if r.section in IN_TOTAL]
    if value is None or closing == 0 or not counted:
        return
    given = ZERO
    for row in counted[:-1]:
        row.value = (row.quantity * value / closing).quantize(CENT, ROUND_HALF_UP)
        given += row.value
    counted[-1].value = value - given


def _order(row: GodownRow) -> tuple[int, str, str]:
    """By section, godown and batch."""
    return (SECTIONS.index(row.section), (row.godown or "").lower(), (row.batch or "").lower())


def by_godown(
    session: Session, companies: list[int], period: Period, names: set[str] | None = None
) -> ByGodown:
    """Every item, godown and batch at the period's end, in its section, with values at the
    item's rate; and the source's own value of each godown (F-STK-005)."""
    items, _ = _rows(session, companies, period)
    if names is not None:
        items = [r for r in items if r.name in names]
    value_on = _last_within(value_dates(session, companies), period.end)
    values = _values(session, companies, value_on, "item") if value_on else {}
    godown_values = _values(session, companies, value_on, "godown") if value_on else {}
    found = quantities(session, companies, period.end, {r.name for r in items})
    rows: list[GodownRow] = []
    for item in sorted(items, key=lambda r: r.name.lower()):
        mine = [
            GodownRow(section, item.item_id, item.name, item.unit, godown, batch, quantity)
            for (section, name, godown, batch), quantity in found.items()
            if name == item.name
        ]
        mine.sort(key=_order)
        _allocate(mine, values.get(item.name) if values else None, item.closing)
        rows.extend(mine)
    return ByGodown(period.end, value_on, rows, godown_values)
