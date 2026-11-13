"""The Day Book page (ADR-057; Books › Day Book): every voucher of a period as the source's own
Day Book lists it. Formulas F-DAY-001 and F-DAY-002.

The rules come from Tally's own Day Book, recorded day by day on the test company
(tests/fixtures/tally/rules/day_book, 2026-11-13: 24 days, 90 vouchers):

- **Which vouchers:** every voucher of the day that isn't deleted: cancelled and optional ones,
  memoranda, orders and inventory-only vouchers included (Tally's Day Book lists exactly its
  own voucher list).
- **Particulars and amount** (F-DAY-001): the voucher's first ledger entry, its amount in the
  debit column when a debit, else in the credit column (the registers' rule, F-REG-001). A
  voucher of a type that doesn't post to the books but moves stock (a delivery or receipt
  note, a stock journal, a rejection) shows its first stock item and quantity instead: inward
  in the first column, outward in the second; a rejection as a negative quantity in the
  column of the note it reverses (Rejections Out under inward, Rejections In under outward).
  Orders and memoranda show their ledger amount. A cancelled voucher shows "(cancelled)" and
  no amount, as Tally does.
- **Order:** by date; then type by type in the source's order of voucher types, a custom type
  right after the type it derives from (`voucher_types.sort_position`); then by number.
- **Tags** (not in Tally's export; the developer's decision, 2026-11-13): "optional",
  "memorandum" and "order" for vouchers that don't change the books. Particulars stays exactly
  as the source shows it.
- **Counts** (F-DAY-002): the vouchers of each voucher type in the period.

At most `LIMIT` vouchers, the earliest first; `truncated` says when there were more.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import accounting as A  # noqa: N812
from core.report_periods import Period

LIMIT = 20_000
CANCELLED = "(cancelled)"  # as the source's Day Book writes a cancelled voucher's Particulars
MEMORANDUM_TYPES = frozenset({"Memorandum"})  # standard voucher types (VoucherType.standard_type)
ORDER_TYPES = frozenset(
    {"Sales Order", "Purchase Order", "Job Work In Order", "Job Work Out Order"}
)
# A rejection reverses a note: shown negative in that note's column (Tally's Day Book).
REJECTION_COLUMNS = {"Rejections Out": "inward", "Rejections In": "outward"}


@dataclass
class DayBookRow:
    voucher_id: int
    company: int
    on: date
    particulars: str
    voucher_type: str
    number: str | None
    debit: Decimal | None = None
    credit: Decimal | None = None
    inward: Decimal | None = None  # a quantity, for a voucher without ledger entries
    outward: Decimal | None = None
    unit: str | None = None
    narration: str | None = None
    party: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class DayBook:
    rows: list[DayBookRow]
    counts: dict[str, int]  # voucher type -> vouchers in the period (F-DAY-002)
    truncated: bool


def day_book(session: Session, companies: list[int], period: Period) -> DayBook:
    vouchers = session.execute(
        select(
            A.Voucher.id, A.Voucher.entity_id, A.Voucher.voucher_date, A.VoucherType.name,
            A.VoucherType.standard_type, A.Voucher.voucher_number, A.Voucher.narration,
            A.Voucher.is_cancelled, A.Voucher.is_optional, A.Party.name,
            A.VoucherType.is_accounting, A.VoucherType.moves_stock, A.VoucherType.sort_position,
            A.VoucherType.entity_id,
        )
        .join(A.VoucherType, A.VoucherType.id == A.Voucher.voucher_type_id)
        .outerjoin(A.Party, A.Party.id == A.Voucher.party_id)
        .where(
            A.Voucher.entity_id.in_(companies),
            A.Voucher.is_deleted.is_(False),
            A.Voucher.voucher_date >= period.start,
            A.Voucher.voucher_date <= period.end,
        )
    ).all()  # fmt: skip
    vouchers = sorted(vouchers, key=_order(session, companies))
    counts = Counter(v[3] for v in vouchers)
    truncated = len(vouchers) > LIMIT
    vouchers = vouchers[:LIMIT]
    ids = [v[0] for v in vouchers]
    stock_only = {v[0] for v in vouchers if not v[10] and v[11]}  # moves stock, no books
    first_lines = _first_ledger_lines(session, ids)
    first_items = _first_items(session, ids)
    rows = []
    for (
        vid,
        entity,
        on,
        vtype,
        standard,
        number,
        narration,
        cancelled,
        optional,
        party,
        *_,
    ) in vouchers:
        row = DayBookRow(vid, entity, on, "", vtype, number, narration=narration, party=party,
                         tags=_tags(standard, optional))  # fmt: skip
        if cancelled:
            row.particulars = CANCELLED
        elif vid in first_items and (vid in stock_only or vid not in first_lines):
            row.particulars, quantity, row.unit = first_items[vid]  # a stock voucher
            _quantity(row, quantity, standard)
        elif vid in first_lines:
            row.particulars, amount = first_lines[vid]
            row.debit, row.credit = (amount, None) if amount > 0 else (None, -amount)
        rows.append(row)
    return DayBook(rows, dict(counts), truncated)


def _order(session: Session, companies: list[int]):  # noqa: ANN202
    """The sort key of a voucher row: date, its type's place (a custom type right after the
    standard type it derives from), the number (numbers as numbers), its id."""
    standard_positions = {
        (entity, name): position
        for entity, name, position in session.execute(
            select(A.VoucherType.entity_id, A.VoucherType.name, A.VoucherType.sort_position)
            .where(A.VoucherType.entity_id.in_(companies))
        )
    }  # fmt: skip

    def key(v) -> tuple:  # noqa: ANN001
        own = v[12] if v[12] is not None else 10**9
        parent = standard_positions.get((v[13], v[4]), own) if v[4] else own
        number = v[5] or ""
        return (v[2], parent if parent is not None else own, own,
                (0, int(number), "") if number.isdigit() else (1, 0, number), v[0])  # fmt: skip

    return key


def _quantity(row: DayBookRow, quantity: Decimal, standard: str | None) -> None:
    """A stock voucher's quantity in its column; a rejection negative in the column of the
    note it reverses."""
    column = REJECTION_COLUMNS.get(standard or "")
    if column == "inward":
        row.inward = quantity
    elif column == "outward":
        row.outward = -quantity
    elif quantity > 0:
        row.inward = quantity
    else:
        row.outward = -quantity


def _tags(standard: str | None, optional: bool) -> list[str]:
    tags = []
    if optional:
        tags.append("optional")
    if standard in MEMORANDUM_TYPES:
        tags.append("memorandum")
    if standard in ORDER_TYPES:
        tags.append("order")
    return tags


def _first_ledger_lines(session: Session, ids: list[int]) -> dict[int, tuple[str, Decimal]]:
    """Each voucher's first ledger entry: (ledger name, amount; debit positive)."""
    found: dict[int, tuple[str, Decimal]] = {}
    for start in range(0, len(ids), 1000):
        chunk = ids[start : start + 1000]
        first = (
            select(A.VoucherLine.voucher_id, func.min(A.VoucherLine.line_no).label("line_no"))
            .where(A.VoucherLine.voucher_id.in_(chunk))
            .group_by(A.VoucherLine.voucher_id)
            .subquery()
        )
        for vid, name, amount in session.execute(
            select(A.VoucherLine.voucher_id, A.Ledger.name, A.VoucherLine.amount)
            .join(first, (first.c.voucher_id == A.VoucherLine.voucher_id)
                  & (first.c.line_no == A.VoucherLine.line_no))
            .join(A.Ledger, A.Ledger.id == A.VoucherLine.ledger_id)
        ):  # fmt: skip
            found[vid] = (name, Decimal(amount))
    return found


def _first_items(session: Session, ids: list[int]) -> dict[int, tuple[str, Decimal, str | None]]:
    """Each voucher's first stock line: (item name, quantity; inward positive, its unit)."""
    found: dict[int, tuple[str, Decimal, str | None]] = {}
    for start in range(0, len(ids), 1000):
        chunk = ids[start : start + 1000]
        first = (
            select(A.InventoryLine.voucher_id, func.min(A.InventoryLine.line_no).label("line_no"))
            .where(A.InventoryLine.voucher_id.in_(chunk))
            .group_by(A.InventoryLine.voucher_id)
            .subquery()
        )
        for vid, name, quantity, unit in session.execute(
            select(A.InventoryLine.voucher_id, A.Item.name, A.InventoryLine.quantity,
                   A.Unit.symbol)
            .join(first, (first.c.voucher_id == A.InventoryLine.voucher_id)
                  & (first.c.line_no == A.InventoryLine.line_no))
            .join(A.Item, A.Item.id == A.InventoryLine.item_id)
            .outerjoin(A.Unit, A.Unit.id == A.InventoryLine.unit_id)
        ):  # fmt: skip
            found[vid] = (name, Decimal(quantity), unit)
    return found
