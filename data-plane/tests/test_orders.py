"""Orders (data completion, part 4), on the seeded test company's recordings of 2026-11-06
(tests/fixtures/tally/rules/data-completion): sales order SO-1 (ORD-1) with an invoice for
part of it (ORD-1-INV), purchase order PO-1 (ORD-2) with its invoice (ORD-2-INV)."""

from datetime import date

from connectors.tally import mapping, parser
from core.canonical import CanonicalOrderRef, CanonicalVoucher
from core.transform import ORDER_TYPE_BY_BASE
from tests.conftest import FIXTURES

OCTOBER = FIXTURES / "tally" / "rules" / "data-completion" / "vouchers_2026-10.xml"


def _voucher(marker: str) -> CanonicalVoucher:
    for element in parser.objects(parser.parse_response(OCTOBER.read_bytes()), "VOUCHER"):
        if f"[lb-seed:{marker}]" in (element.findtext("NARRATION") or ""):
            return mapping.voucher(element, parser.source_key(element))
    raise AssertionError(f"{marker} not recorded")


def test_an_orders_lines_carry_its_number_and_due_date() -> None:
    for marker, number in (("ORD-1", "SO-1"), ("ORD-2", "PO-1")):
        order = _voucher(marker)
        assert order.orders == ()  # an order isn't made against another
        assert {(x.order_number, x.order_due_date) for x in order.inventory} == {
            (number, date(2026, 10, 31))
        }


def test_an_invoice_names_the_order_it_is_made_against() -> None:
    for marker, number in (("ORD-1-INV", "SO-1"), ("ORD-2-INV", "PO-1")):
        invoice = _voucher(marker)
        assert invoice.orders == (CanonicalOrderRef(number, date(2026, 10, 1)),)
        assert {x.order_number for x in invoice.inventory} == {number}


def test_a_voucher_without_an_order_has_none() -> None:
    voucher = _voucher("BILL-1")
    assert voucher.orders == ()
    assert all(x.order_number is None and x.order_due_date is None for x in voucher.inventory)


def test_an_order_due_in_days_counts_from_the_vouchers_date() -> None:
    body = OCTOBER.read_bytes().replace(
        b'P="31-Oct-26">31-Oct-26</ORDERDUEDATE>', b'P="15 Days">15 Days</ORDERDUEDATE>'
    )
    for element in parser.objects(parser.parse_response(body), "VOUCHER"):
        if "[lb-seed:ORD-1]" in (element.findtext("NARRATION") or ""):
            order = mapping.voucher(element, "k")
            assert {x.order_due_date for x in order.inventory} == {date(2026, 10, 16)}


def test_sales_and_purchase_side_vouchers_look_for_their_own_orders() -> None:
    assert {ORDER_TYPE_BY_BASE[b] for b in ("sales", "credit_note", "delivery_note")} == {
        "Sales Order"
    }
    assert {ORDER_TYPE_BY_BASE[b] for b in ("purchase", "debit_note", "receipt_note")} == {
        "Purchase Order"
    }
