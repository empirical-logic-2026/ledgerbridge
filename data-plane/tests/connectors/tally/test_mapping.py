"""Ledger mapping rules that the test company's fixtures don't cover."""

import xml.etree.ElementTree as ET  # noqa: N817
from decimal import Decimal

from connectors.base import SourceRecord
from connectors.tally import mapping
from core.canonical import CanonicalLedger


def _ledger(body: str) -> CanonicalLedger:
    payload = f'<LEDGER NAME="L"><NAME>L</NAME>{body}</LEDGER>'
    records = mapping.to_canonical(SourceRecord("co", "ledger", "guid", 1, "xml", payload))
    return next(r for r in records if isinstance(r, CanonicalLedger))


def test_duties_and_taxes_default_by_tax_type() -> None:
    gst = _ledger(
        "<PARENT>Duties &amp; Taxes</PARENT><TAXTYPE>GST</TAXTYPE>"
        "<GSTDUTYHEAD>Integrated Tax</GSTDUTYHEAD>"
    )
    assert (gst.tax_type, gst.default_standard_account_code, gst.warnings) == ("igst", "1250", ())
    for tax in ("TDS", "TCS"):
        ledger = _ledger(f"<PARENT>Duties &amp; Taxes</PARENT><TAXTYPE>{tax}</TAXTYPE>")
        assert (ledger.tax_type, ledger.default_standard_account_code) == (tax.lower(), "1260")
    other = _ledger("<PARENT>Duties &amp; Taxes</PARENT><TAXTYPE>Others</TAXTYPE>")
    assert (other.tax_type, other.default_standard_account_code) == (None, None)


def test_empty_duty_head_is_central_tax_for_gst_only_and_warns() -> None:
    gst = _ledger("<PARENT>Duties &amp; Taxes</PARENT><TAXTYPE>GST</TAXTYPE>")
    assert gst.tax_type == "cgst"
    assert gst.warnings == (mapping.EMPTY_DUTY_HEAD_WARNING,)
    vat = _ledger("<PARENT>Duties &amp; Taxes</PARENT><TAXTYPE>VAT</TAXTYPE>")
    assert (vat.tax_type, vat.warnings) == ("vat", ())
    plain = _ledger("<PARENT>Rent</PARENT><TAXTYPE>Others</TAXTYPE>")
    assert (plain.tax_type, plain.warnings) == (None, ())


def test_deposits_map_to_long_term_loans_and_advances() -> None:
    assert mapping.STANDARD_ACCOUNT_BY_GROUP["Deposits (Asset)"] == "1160"
    assert mapping.STANDARD_ACCOUNT_BY_GROUP["Duties & Taxes"] == mapping.UNMAPPED


def _inventory_entry(quantity: str, deemed_positive: str, batches: str) -> list:
    entry = ET.fromstring(
        "<ALLINVENTORYENTRIES.LIST><STOCKITEMNAME>Item</STOCKITEMNAME>"
        f"<ISDEEMEDPOSITIVE>{deemed_positive}</ISDEEMEDPOSITIVE>"
        f"<ACTUALQTY>{quantity}</ACTUALQTY><AMOUNT>-90.00</AMOUNT>{batches}"
        "</ALLINVENTORYENTRIES.LIST>"
    )
    return mapping._inventory_lines(entry, None)


def _batch(godown: str, quantity: str, amount: str = "") -> str:
    value = f"<AMOUNT>{amount}</AMOUNT>" if amount else ""
    return (
        f"<BATCHALLOCATIONS.LIST><GODOWNNAME>{godown}</GODOWNNAME>"
        f"<ACTUALQTY>{quantity}</ACTUALQTY>{value}</BATCHALLOCATIONS.LIST>"
    )


def test_a_zero_quantity_entry_whose_batches_lack_amounts_stays_whole() -> None:
    """The entry's amount can't be shared by quantity when the entry has none: one line,
    instead of a division by zero that failed the whole voucher."""
    lines = _inventory_entry(" 0 Nos", "No", _batch("A", " 2 Nos") + _batch("B", " 1 Nos"))
    assert len(lines) == 1
    assert lines[0].amount == Decimal("90.00")


def test_a_zero_quantity_outward_entry_splits_with_the_entrys_direction() -> None:
    """The batches of an outward entry go out, even when the entry's quantity is zero
    (its sign used to come from that quantity, which has none)."""
    batches = _batch("A", " 2 Nos", "-60.00") + _batch("B", " 1 Nos", "-30.00")
    lines = _inventory_entry(" 0 Nos", "No", batches)
    assert [(line.godown_name, line.quantity) for line in lines] == [
        ("A", Decimal(-2)),
        ("B", Decimal(-1)),
    ]
