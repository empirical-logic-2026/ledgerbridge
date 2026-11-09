"""GST details (data completion, part 5), on the seeded test company's recordings of
2026-11-06 (tests/fixtures/tally/rules/data-completion): a GST invoice with an IRN and an
e-way bill (BILL-1), Gizmo's HSN and rates, the parties' registration types and the
company's tax units."""

import re
import xml.etree.ElementTree as ET  # noqa: N817
from datetime import date
from decimal import Decimal

from connectors.tally import envelopes, mapping, parser
from core.canonical import CanonicalGstRate, CanonicalLedger, CanonicalVoucher
from tests.conftest import FIXTURES

RULES = FIXTURES / "tally" / "rules" / "data-completion"


def _objects(file: str, tag: str, body: bytes | None = None) -> list[ET.Element]:
    return parser.objects(parser.parse_response(body or (RULES / file).read_bytes()), tag)


def _bill_1(body: bytes | None = None) -> CanonicalVoucher:
    for element in _objects("vouchers_2026-10.xml", "VOUCHER", body):
        if "[lb-seed:BILL-1]" in (element.findtext("NARRATION") or ""):
            return mapping.voucher(element, parser.source_key(element))
    raise AssertionError("BILL-1 not recorded")


def test_a_gst_invoice_keeps_its_registration_supply_irn_and_eway_bill() -> None:
    v = _bill_1()
    assert (v.gst_registration, v.place_of_supply) == ("Registration", "Karnataka")
    assert v.irn is not None and len(v.irn) == 64
    assert (v.irn_ack_number, v.irn_date) == ("112610012345678", date(2026, 10, 1))
    assert (v.eway_bill_number, v.eway_bill_date) == ("331001234567", date(2026, 10, 1))


def test_a_line_taking_its_rate_from_the_item_has_none_of_its_own() -> None:
    """Tally lists every duty head at 0 on such a line: those aren't rates."""
    v = _bill_1()
    assert all(x.gst_rates == () for x in v.inventory)
    assert all(x.gst_rates == () for x in v.lines)


def test_a_lines_own_rates_are_kept_per_duty_head() -> None:
    body = (RULES / "vouchers_2026-10.xml").read_bytes()
    marker = body.index(b"[lb-seed:BILL-1]")
    zero = re.compile(rb"(<GSTRATEDUTYHEAD[^>]*>CGST</GSTRATEDUTYHEAD>\s*<GSTRATE[^>]*>)0<")
    found = zero.search(body, marker)  # the invoice's item line
    assert found is not None
    body = body[: found.start()] + found.group(1) + b" 9<" + body[found.end() :]
    (line,) = _bill_1(body).inventory
    assert CanonicalGstRate("CGST", Decimal(9)) in line.gst_rates
    assert {r.duty_head for r in line.gst_rates} == {
        "CGST",
        "SGST/UTGST",
        "IGST",
        "Cess",
        "State Cess",
    }


def _item(name: str):  # noqa: ANN202
    for element in _objects("stock_items.xml", "STOCKITEM"):
        if parser.object_name(element) == name:
            return mapping.stock_item(element, parser.source_key(element))
    raise AssertionError(f"{name} not recorded")


def test_an_items_hsn_taxability_and_integrated_rate() -> None:
    gizmo = _item("Gizmo")
    assert (gizmo.hsn_code, gizmo.gst_rate, gizmo.gst_taxability) == (
        "8471",
        Decimal(18),
        "Taxable",
    )
    assert gizmo.gst_classification is None
    widget = _item("Widget")
    assert (widget.hsn_code, widget.gst_rate, widget.gst_taxability) == (None, None, None)


def test_the_latest_gst_details_apply() -> None:
    element = ET.fromstring(  # noqa: S314 - a literal
        "<STOCKITEM NAME='X'><GUID>g</GUID>"
        "<GSTDETAILS.LIST><APPLICABLEFROM>20250401</APPLICABLEFROM><HSNCODE>1111</HSNCODE>"
        "<STATEWISEDETAILS.LIST><STATENAME>Any</STATENAME><RATEDETAILS.LIST>"
        "<GSTRATEDUTYHEAD>IGST</GSTRATEDUTYHEAD><GSTRATE> 12</GSTRATE></RATEDETAILS.LIST>"
        "</STATEWISEDETAILS.LIST></GSTDETAILS.LIST>"
        "<GSTDETAILS.LIST><APPLICABLEFROM>20260401</APPLICABLEFROM><HSNCODE>2222</HSNCODE>"
        "<STATEWISEDETAILS.LIST><STATENAME>Any</STATENAME>"
        "<RATEDETAILS.LIST><GSTRATEDUTYHEAD>CGST</GSTRATEDUTYHEAD><GSTRATE> 2.5</GSTRATE>"
        "</RATEDETAILS.LIST><RATEDETAILS.LIST><GSTRATEDUTYHEAD>SGST/UTGST</GSTRATEDUTYHEAD>"
        "<GSTRATE> 2.5</GSTRATE></RATEDETAILS.LIST></STATEWISEDETAILS.LIST></GSTDETAILS.LIST>"
        "<HSNDETAILS.LIST><APPLICABLEFROM>20260401</APPLICABLEFROM>"
        "<HSNCLASSIFICATIONNAME>Food</HSNCLASSIFICATIONNAME></HSNDETAILS.LIST></STOCKITEM>"
    )
    item = mapping.stock_item(element, "g")
    assert (item.hsn_code, item.gst_rate, item.gst_classification) == ("2222", Decimal(5), "Food")


def test_a_partys_gst_registration_type() -> None:
    types = {}
    for element in _objects("ledgers.xml", "LEDGER"):
        name = parser.object_name(element)
        if name in ("Customer Theta GST", "Vendor Iota GST", "Cash"):
            records = mapping.ledger(element, parser.source_key(element), "e")
            (ledger,) = [r for r in records if isinstance(r, CanonicalLedger)]
            types[name] = ledger.party.gst_registration_type if ledger.party else None
    assert types == {
        "Customer Theta GST": "Regular",
        "Vendor Iota GST": "Composition",
        "Cash": None,
    }


def test_the_companys_tax_units() -> None:
    units = {
        u.name: u
        for u in (
            mapping.tax_unit(e, parser.source_key(e)) for e in _objects("tax_units.xml", "TAXUNIT")
        )
    }
    assert set(units) == {"Default Tax Unit", "Registration"}
    gst = units["Registration"]
    assert (gst.used_for, gst.registration_type, gst.registered_from, gst.is_primary) == (
        "GST",
        "Regular",
        date(2026, 4, 1),
        False,
    )
    assert units["Default Tax Unit"].is_primary


def test_tax_units_are_a_master_after_the_cost_centres() -> None:
    assert envelopes.MASTER_SPECS[-1] is envelopes.TAX_UNITS
    assert envelopes.TAX_UNITS.object_type == "tax_unit"
    assert not envelopes.denied_in(envelopes.TAX_UNITS.fetch)
    assert not envelopes.denied_in(envelopes.VOUCHERS.fetch)
