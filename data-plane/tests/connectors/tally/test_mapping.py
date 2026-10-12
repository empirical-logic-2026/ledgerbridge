"""Ledger mapping rules that the test company's fixtures don't cover."""

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
