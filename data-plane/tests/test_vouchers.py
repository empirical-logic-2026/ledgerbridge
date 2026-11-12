"""The voucher page (core/vouchers.py, F-VCH-001): one voucher's header, ledger lines, bill
allocations and stock lines, on the test company's recording; none outside the companies."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.vouchers import voucher_page


def _vouchers(db: Session) -> list[A.Voucher]:
    return list(db.scalars(select(A.Voucher).where(A.Voucher.is_deleted.is_(False))))


def test_every_voucher_balances_and_shows_its_lines(db: Session, synced: S.Connection) -> None:
    entity = db.scalars(select(A.Entity)).one().id
    vouchers = _vouchers(db)
    assert vouchers
    for voucher in vouchers:
        page = voucher_page(db, [entity], voucher.id)
        assert page is not None and page.number == voucher.voucher_number
        if page.cancelled:
            assert page.debit == page.credit == 0  # Tally keeps no lines of a cancelled one
        elif not page.optional:
            assert page.lines and page.debit == page.credit > 0, voucher.voucher_number


def test_an_invoice_shows_its_bills_and_stock(db: Session, synced: S.Connection) -> None:
    entity = db.scalars(select(A.Entity)).one().id
    with_bill = db.scalar(
        select(A.VoucherLine.voucher_id).join(
            A.BillAllocation, A.BillAllocation.voucher_line_id == A.VoucherLine.id
        )
    )
    page = voucher_page(db, [entity], with_bill)
    assert page is not None and page.bills
    assert all(b.amount != 0 for b in page.bills)
    with_stock = db.scalar(select(A.InventoryLine.voucher_id))
    if with_stock is not None:
        stock = voucher_page(db, [entity], with_stock)
        assert stock is not None and stock.stock
        assert all(isinstance(s.quantity, Decimal) for s in stock.stock)


def test_a_voucher_outside_the_companies_is_not_shown(db: Session, synced: S.Connection) -> None:
    voucher = _vouchers(db)[0]
    assert voucher_page(db, [voucher.entity_id + 999], voucher.id) is None
    assert voucher_page(db, [voucher.entity_id], 999_999) is None
