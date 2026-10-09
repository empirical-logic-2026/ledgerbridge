import xml.etree.ElementTree as ET  # noqa: N817
from datetime import date

import pytest

from connectors.tally import envelopes
from connectors.tally.client import TallyClient


@pytest.mark.parametrize("spec", envelopes.ALL_SPECS, ids=lambda s: s.collection_id)
def test_every_request_is_an_export(spec: envelopes.CollectionSpec) -> None:
    request = envelopes.collection_request(spec, company="A & B Ltd")
    root = ET.fromstring(request)
    assert root.findtext("HEADER/TALLYREQUEST") == "Export"
    assert root.findtext("HEADER/ID") == spec.collection_id
    assert root.findtext(".//COLLECTION/TYPE") == spec.tally_type
    assert root.findtext(".//SVCURRENTCOMPANY") == "A & B Ltd"
    assert "GUID" in root.findtext(".//COLLECTION/FETCH")


def test_voucher_request_uses_exclusive_end_on_the_first() -> None:
    # A 30-day month: Tally must never see the 30th (Educational mode ignores it).
    request = envelopes.collection_request(
        envelopes.VOUCHERS, company="X", period=(date(2024, 4, 1), date(2024, 4, 30))
    )
    root = ET.fromstring(request)
    assert root.findtext(".//SVFROMDATE") == "20240401"
    assert root.findtext(".//SVTODATE") == "20240501"
    assert root.findtext(".//COLLECTION/FILTER") == "LBInPeriod"
    assert root.findtext(".//SYSTEM") == "$Date >= ##SVFromDate AND $Date < ##SVToDate"


def test_client_refuses_non_export_requests() -> None:
    client = TallyClient("http://localhost:9000")
    with pytest.raises(ValueError, match="Only Tally Export"):
        client.post("<ENVELOPE><HEADER><TALLYREQUEST>Import</TALLYREQUEST></HEADER></ENVELOPE>")


def test_balance_request_computes_isdr_without_dates() -> None:
    root = ET.fromstring(envelopes.collection_request(envelopes.LEDGER_BALANCES, company="X"))
    computes = [c.text for c in root.iter("COMPUTE")]
    assert "LBCLOSINGISDR : $$IsDr:$ClosingBalance" in computes
    assert root.find(".//COLLECTION/FILTER") is None
    assert root.find(".//SVTODATE") is None
