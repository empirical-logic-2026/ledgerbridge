"""The base-currency books before and after a rebuild: every base amount and balance
(source-independent; developer's request, 2026-10-24).

Where it fits: `transform rebuild` (workers/cli.py) takes a `snapshot` of a connection's
base figures before rebuilding every stored record with the current code, and another
after, and `compare`s them. A change that should only add information beside the books
(e.g. foreign-currency fields, FX-001) must leave the books identical: each voucher's lines
(line number, ledger, base amount, whether it counts) and each ledger's opening and
balance, all by the source's keys. Only counts are reported.
"""

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import accounting as A  # noqa: N812


@dataclass
class BaseFigures:
    vouchers: dict[str, str] = field(default_factory=dict)  # voucher key -> digest of its lines
    ledgers: dict[str, tuple[Decimal, Decimal]] = field(default_factory=dict)  # (opening, balance)


@dataclass
class BaseComparison:
    vouchers: int = 0  # compared (before and after together)
    vouchers_differing: int = 0
    ledgers: int = 0
    ledgers_differing: int = 0

    @property
    def unchanged(self) -> bool:
        return not (self.vouchers_differing or self.ledgers_differing)


def snapshot(session: Session, connection_id: int) -> BaseFigures:
    """The connection's base figures, by the source's keys."""
    figures = BaseFigures()
    lines: dict[str, hashlib._Hash] = defaultdict(hashlib.sha256)
    rows = session.execute(
        select(
            A.Voucher.source_key,
            A.Voucher.is_deleted,
            A.VoucherLine.line_no,
            A.Ledger.source_key,
            A.VoucherLine.amount,
            A.VoucherLine.is_effective,
        )
        .join(A.Voucher, A.Voucher.id == A.VoucherLine.voucher_id)
        .join(A.Ledger, A.Ledger.id == A.VoucherLine.ledger_id)
        .where(A.Voucher.connection_id == connection_id)
        .order_by(A.Voucher.source_key, A.VoucherLine.line_no)
        .execution_options(yield_per=10_000)
    )
    for key, deleted, no, ledger, amount, effective in rows:
        lines[key].update(f"{deleted}|{no}|{ledger}|{Decimal(amount):.4f}|{effective};".encode())
    figures.vouchers = {key: digest.hexdigest() for key, digest in lines.items()}
    moved = (
        select(A.VoucherLine.ledger_id, func.sum(A.VoucherLine.amount).label("moved"))
        .where(A.VoucherLine.is_effective.is_(True))
        .group_by(A.VoucherLine.ledger_id)
        .subquery()
    )
    for key, opening, total in session.execute(
        select(A.Ledger.source_key, A.Ledger.opening_balance, func.coalesce(moved.c.moved, 0))
        .outerjoin(moved, moved.c.ledger_id == A.Ledger.id)
        .where(A.Ledger.connection_id == connection_id)
    ):
        figures.ledgers[key] = (Decimal(opening), Decimal(opening) + Decimal(total))
    return figures


def compare(before: BaseFigures, after: BaseFigures) -> BaseComparison:
    """How many vouchers and ledgers were compared, and how many differ (missing on one
    side counts as differing)."""
    vouchers = before.vouchers.keys() | after.vouchers.keys()
    ledgers = before.ledgers.keys() | after.ledgers.keys()
    return BaseComparison(
        vouchers=len(vouchers),
        vouchers_differing=sum(
            1 for k in vouchers if before.vouchers.get(k) != after.vouchers.get(k)
        ),
        ledgers=len(ledgers),
        ledgers_differing=sum(1 for k in ledgers if before.ledgers.get(k) != after.ledgers.get(k)),
    )
