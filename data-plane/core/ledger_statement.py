"""The Ledger statement page (ADR-055; Books › Ledger statement): one ledger's opening
balance, every entry of a period with the other side, debit, credit and the running
balance, and the closing balance, as the source's ledger report shows it (Tally's Ledger
Vouchers). Formulas F-LED-001 to F-LED-004 in docs/formula-sheet.md.

- **Opening** (F-LED-001): the ledger's opening balance plus its entries before the period.
  An income or expense ledger starts each financial year at nil (earlier years went into
  Profit & Loss A/c, as on the Trial Balance page: F-TB-003), so its opening is only its
  entries from the start of the period's financial year.
- **An entry** (F-LED-002): one row per voucher, the ledger's lines in it added up; a debit
  in the debit column, a credit in the credit column. Particulars: the voucher's first
  ledger other than this one (the source's "By"/"To"). Cancelled and optional vouchers have
  no effective lines, so they don't appear (as in the source's report).
- **Running balance** (F-LED-003): the opening plus each entry in date order.
- **Closing** (F-LED-004): the opening plus the period's entries. A foreign-currency ledger
  with a revaluation stored for the period's end (core/statements.py) also gets the
  source's calculated row at that date, "Unadjusted Forex Gain/Loss" (no voucher), so the
  closing is the revalued balance, as the source's report shows it.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.dates import financial_year_ends
from core.models import accounting as A  # noqa: N812
from core.report_periods import Period
from core.statements import UNADJUSTED_FOREX

ZERO = Decimal(0)
LIMIT = 5000  # entries shown; the totals always cover the whole period
INCOME_EXPENSE = ("income", "expense")


@dataclass
class Entry:
    voucher_id: int | None  # None: the source's calculated row (a revaluation)
    on: date
    voucher_type: str
    number: str | None
    particulars: str
    narration: str | None
    amount: Decimal  # debit positive
    running: Decimal = ZERO


@dataclass
class LedgerStatement:
    ledger_id: int
    name: str
    company: int
    groups: list[str]  # its group and those above, top first
    nature: str | None
    opening: Decimal
    opening_from: date  # the opening is the balance at the start of this day
    entries: list[Entry] = field(default_factory=list)
    debit: Decimal = ZERO  # the period's debits (F-LED-002)
    credit: Decimal = ZERO
    closing: Decimal = ZERO
    truncated: bool = False


def ledger_statement(session: Session, ledger_id: int, period: Period) -> LedgerStatement | None:
    ledger = session.get(A.Ledger, ledger_id)
    if ledger is None or ledger.is_deleted:
        return None
    groups, nature = _groups(session, ledger.group_id)
    start = _counted_from(session, ledger, nature, period.start)
    opening = _moved(session, ledger_id, start, period.start, before=True)
    if start is None:  # from the books' beginning: the ledger's own opening too
        opening += ledger.opening_balance
    found = LedgerStatement(
        ledger.id, ledger.name, ledger.entity_id, groups, nature, opening, period.start
    )
    rows, found.truncated = _entries(session, ledger_id, period)
    revaluation = _revaluation(session, ledger_id, period.end, opening + sum(
        (e.amount for e in rows), ZERO))  # fmt: skip
    if revaluation is not None:
        rows.append(revaluation)
    running = opening
    for entry in rows:
        running += entry.amount
        entry.running = running
    found.entries = rows
    found.debit = sum((e.amount for e in rows if e.amount > 0), ZERO)
    found.credit = -sum((e.amount for e in rows if e.amount < 0), ZERO)
    found.closing = opening + found.debit - found.credit
    if found.truncated:  # the totals still cover every entry of the period
        found.closing = opening + _moved(session, ledger_id, period.start, period.end) + (
            revaluation.amount if revaluation else ZERO)  # fmt: skip
    return found


def _groups(session: Session, group_id: int) -> tuple[list[str], str | None]:
    """The ledger's group and those above it (top first), and the top group's nature."""
    names, nature, seen = [], None, set()
    current: int | None = group_id
    while current is not None and current not in seen:
        seen.add(current)
        group = session.get(A.AccountGroup, current)
        if group is None:
            break
        names.append(group.name)
        nature = group.nature or nature
        current = group.parent_id
    return list(reversed(names)), nature


def _counted_from(
    session: Session, ledger: A.Ledger, nature: str | None, start: date
) -> date | None:
    """Where the opening's entries start: an income or expense ledger's financial year start
    (after a year end), else the books' beginning (None)."""
    if nature not in INCOME_EXPENSE:
        return None
    entity = session.get(A.Entity, ledger.entity_id)
    if entity is None:
        return None
    ends = financial_year_ends(entity.books_from, entity.fy_start_month, start)
    return ends[-1] + timedelta(days=1) if ends else None


def _effective(ledger_id: int):  # noqa: ANN202
    return (
        A.VoucherLine.ledger_id == ledger_id,
        A.VoucherLine.is_effective.is_(True),
        A.Voucher.is_deleted.is_(False),
    )


def _moved(
    session: Session, ledger_id: int, start: date | None, end: date, before: bool = False
) -> Decimal:
    """The ledger's lines from `start` (None: the beginning) up to `end` (excluded when
    `before`)."""
    query = (
        select(func.coalesce(func.sum(A.VoucherLine.amount), 0))
        .join(A.Voucher, A.Voucher.id == A.VoucherLine.voucher_id)
        .where(*_effective(ledger_id))
    )
    if start is not None:
        query = query.where(A.VoucherLine.voucher_date >= start)
    query = query.where(
        A.VoucherLine.voucher_date < end if before else A.VoucherLine.voucher_date <= end
    )
    return Decimal(session.scalar(query) or 0)


def _entries(session: Session, ledger_id: int, period: Period) -> tuple[list[Entry], bool]:
    """One row per voucher in the period, the earliest first (then as stored)."""
    rows = session.execute(
        select(
            A.Voucher.id, A.Voucher.voucher_date, A.VoucherType.name, A.Voucher.voucher_number,
            A.Voucher.narration, func.sum(A.VoucherLine.amount),
        )
        .join(A.Voucher, A.Voucher.id == A.VoucherLine.voucher_id)
        .join(A.VoucherType, A.VoucherType.id == A.Voucher.voucher_type_id)
        .where(
            *_effective(ledger_id),
            A.VoucherLine.voucher_date >= period.start,
            A.VoucherLine.voucher_date <= period.end,
        )
        .group_by(
            A.Voucher.id, A.Voucher.voucher_date, A.VoucherType.name, A.Voucher.voucher_number,
            A.Voucher.narration,
        )
        .order_by(A.Voucher.voucher_date, A.Voucher.id)
        .limit(LIMIT + 1)
    ).all()  # fmt: skip
    truncated = len(rows) > LIMIT
    rows = rows[:LIMIT]
    other = other_sides(session, [r[0] for r in rows], [ledger_id])
    return [
        Entry(vid, on, vtype, number, other.get(vid, ""), narration, Decimal(amount))
        for vid, on, vtype, number, narration, amount in rows
    ], truncated


def other_sides(session: Session, voucher_ids: list[int], ledger_ids: list[int]) -> dict[int, str]:
    """Each voucher's first ledger not among `ledger_ids`: the statement's Particulars."""
    found: dict[int, str] = {}
    for start in range(0, len(voucher_ids), 1000):
        chunk = voucher_ids[start : start + 1000]
        rows = session.execute(
            select(A.VoucherLine.voucher_id, A.Ledger.name)
            .join(A.Ledger, A.Ledger.id == A.VoucherLine.ledger_id)
            .where(A.VoucherLine.voucher_id.in_(chunk), A.VoucherLine.ledger_id.not_in(ledger_ids))
            .order_by(A.VoucherLine.voucher_id, A.VoucherLine.line_no)
        )
        for vid, name in rows:
            found.setdefault(vid, name)
    return found


def _revaluation(session: Session, ledger_id: int, end: date, book: Decimal) -> Entry | None:
    """The source's calculated row for a foreign-currency ledger revalued at the period's
    end (the revaluation stored by the statements for that date): revalued less book."""
    revalued = session.scalar(
        select(A.FxRevaluationSnapshot.revalued_value).where(
            A.FxRevaluationSnapshot.ledger_id == ledger_id, A.FxRevaluationSnapshot.as_of == end
        )
    )
    if revalued is None or revalued == book:
        return None
    return Entry(None, end, "", None, UNADJUSTED_FOREX, None, Decimal(revalued) - book)
