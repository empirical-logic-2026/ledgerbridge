"""One voucher, as the dashboard's voucher page shows it (Books › Voucher; RPT-007, RPT-014):
its header, its ledger lines with debit and credit, its bill allocations and its stock lines.
Formulas F-TRN-001, F-STK-008, F-STK-014 and F-VCH-001 in docs/formula-sheet.md. Read only;
the UTR is stored but never shown (as everywhere in the dashboard).
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from core.models import accounting as A  # noqa: N812

ZERO = Decimal(0)


@dataclass
class VoucherLineRow:
    line_no: int
    ledger_id: int
    ledger: str
    amount: Decimal  # debit positive (F-TRN-001)
    effective: bool  # posts to the books
    instrument_number: str | None  # a cheque number


@dataclass
class BillRow:
    ledger: str
    bill_type: str  # new_ref, against_ref, advance, on_account
    bill_name: str | None
    bill_date: date | None
    due_date: date | None
    amount: Decimal  # debit positive


@dataclass
class StockRow:
    line_no: int
    item_id: int
    item: str
    godown: str | None
    other_godown: str | None
    batch: str | None
    quantity: Decimal  # in +, out - (F-STK-014: what it moves in stock)
    rate: Decimal | None
    amount: Decimal  # F-STK-008


@dataclass
class VoucherPage:
    voucher_id: int
    company: int
    date: date
    voucher_type: str
    number: str
    party_id: int | None
    party: str | None
    reference: str | None
    narration: str | None
    cancelled: bool
    optional: bool
    lines: list[VoucherLineRow] = field(default_factory=list)
    bills: list[BillRow] = field(default_factory=list)
    stock: list[StockRow] = field(default_factory=list)

    @property
    def debit(self) -> Decimal:
        """F-VCH-001: the debits of the lines that post (equal to the credits)."""
        return sum((x.amount for x in self.lines if x.effective and x.amount > 0), ZERO)

    @property
    def credit(self) -> Decimal:
        return -sum((x.amount for x in self.lines if x.effective and x.amount < 0), ZERO)


def voucher_page(session: Session, companies: list[int], voucher_id: int) -> VoucherPage | None:
    """The voucher, or None when it isn't in the companies (or is deleted)."""
    found = session.execute(
        select(A.Voucher, A.VoucherType.name, A.Party.name)
        .join(A.VoucherType, A.VoucherType.id == A.Voucher.voucher_type_id)
        .outerjoin(A.Party, A.Party.id == A.Voucher.party_id)
        .where(A.Voucher.id == voucher_id)
    ).first()
    if found is None:
        return None
    voucher, voucher_type, party = found
    if voucher.entity_id not in companies or voucher.is_deleted:
        return None
    page = VoucherPage(
        voucher.id, voucher.entity_id, voucher.voucher_date, voucher_type,
        voucher.voucher_number, voucher.party_id, party, voucher.reference_number,
        voucher.narration, voucher.is_cancelled, voucher.is_optional,
    )  # fmt: skip
    page.lines = [
        VoucherLineRow(no, lid, name, Decimal(amount), bool(effective), cheque)
        for no, lid, name, amount, effective, cheque in session.execute(
            select(A.VoucherLine.line_no, A.Ledger.id, A.Ledger.name, A.VoucherLine.amount,
                   A.VoucherLine.is_effective, A.VoucherLine.instrument_number)
            .join(A.Ledger, A.Ledger.id == A.VoucherLine.ledger_id)
            .where(A.VoucherLine.voucher_id == voucher_id)
            .order_by(A.VoucherLine.line_no)
        )
    ]  # fmt: skip
    page.bills = [
        BillRow(ledger, kind, name, on, due, Decimal(amount))
        for ledger, kind, name, on, due, amount in session.execute(
            select(A.Ledger.name, A.BillAllocation.bill_type, A.BillAllocation.bill_name,
                   A.BillAllocation.bill_date, A.BillAllocation.due_date, A.BillAllocation.amount)
            .join(A.VoucherLine, A.VoucherLine.id == A.BillAllocation.voucher_line_id)
            .join(A.Ledger, A.Ledger.id == A.VoucherLine.ledger_id)
            .where(A.VoucherLine.voucher_id == voucher_id)
            .order_by(A.VoucherLine.line_no, A.BillAllocation.id)
        )
    ]  # fmt: skip
    godown, other = aliased(A.Godown), aliased(A.Godown)
    page.stock = [
        StockRow(no, iid, item, at, there, batch, Decimal(quantity),
                 None if rate is None else Decimal(rate), Decimal(amount))
        for no, iid, item, at, there, batch, quantity, rate, amount in session.execute(
            select(A.InventoryLine.line_no, A.Item.id, A.Item.name, godown.name, other.name,
                   A.InventoryLine.batch_name, A.InventoryLine.stock_quantity,
                   A.InventoryLine.rate, A.InventoryLine.amount)
            .join(A.Item, A.Item.id == A.InventoryLine.item_id)
            .outerjoin(godown, godown.id == A.InventoryLine.godown_id)
            .outerjoin(other, other.id == A.InventoryLine.counterpart_godown_id)
            .where(A.InventoryLine.voucher_id == voucher_id)
            .order_by(A.InventoryLine.line_no)
        )
    ]  # fmt: skip
    return page
