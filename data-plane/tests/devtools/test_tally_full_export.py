"""The full test-company export (devtools/tally_full_export.py) and the field inventory read
from it (devtools/tally_field_inventory.py): the guards, the requests, the recording's
completeness and the generated docs/data-completeness-fields.md."""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from devtools import tally_field_inventory as inventory
from devtools import tally_full_export as export
from devtools.tally_seed.seed import SeedRefusedError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tally"
COMPANIES = (FIXTURES / "companies.xml").read_bytes()


class FakeTally:
    """Answers the company list; records every request."""

    def __init__(self, companies: bytes) -> None:
        self.companies = companies
        self.requests: list[str] = []

    def post(self, request_xml: str) -> bytes:
        self.requests.append(request_xml)
        return self.companies


def _settings(monkeypatch: pytest.MonkeyPatch, app_env: str) -> None:
    monkeypatch.setattr(export, "get_settings", lambda: SimpleNamespace(app_env=app_env))


def test_refuses_outside_the_test_environment(monkeypatch, tmp_path) -> None:
    _settings(monkeypatch, "pilot")
    tally = FakeTally(COMPANIES)
    with pytest.raises(SeedRefusedError, match="APP_ENV"):
        export.record(tally, export.COMPANY, tmp_path)  # type: ignore[arg-type]
    assert len(tally.requests) == 1  # the company list only
    assert not any(tmp_path.iterdir())


def test_refuses_a_second_company_or_another_name(monkeypatch, tmp_path) -> None:
    _settings(monkeypatch, "test")
    text = COMPANIES.decode()
    company = re.search(r"<COMPANY NAME=.*?</COMPANY>", text, re.S)
    assert company is not None
    two = text.replace(company.group(0), company.group(0) * 2).encode()
    with pytest.raises(SeedRefusedError, match="2 companies"):
        export.record(FakeTally(two), export.COMPANY, tmp_path)  # type: ignore[arg-type]
    with pytest.raises(SeedRefusedError, match="does not exactly match"):
        export.record(FakeTally(COMPANIES), "Another Co", tmp_path)  # type: ignore[arg-type]


def test_asks_for_every_field() -> None:
    masters = export.masters_request(export.COMPANY)
    assert "<TALLYREQUEST>Export</TALLYREQUEST>" in masters
    assert "<ACCOUNTTYPE>All Masters</ACCOUNTTYPE>" in masters
    vouchers = export.whole_collection_request(
        "Voucher", export.COMPANY, lists=["ALLLEDGERENTRIES", "ALLLEDGERENTRIES.BANKALLOCATIONS"]
    )
    assert "<NATIVEMETHOD>*</NATIVEMETHOD>" in vouchers
    assert "<FETCH>ALLLEDGERENTRIES.*, ALLLEDGERENTRIES.BANKALLOCATIONS.*</FETCH>" in vouchers


def test_finds_every_sub_list_and_the_connectors() -> None:
    body = (
        b"<ENVELOPE><BODY><DATA><COLLECTION><VOUCHER><DATE>20260901</DATE>"
        b"<ALLLEDGERENTRIES.LIST><BANKALLOCATIONS.LIST><NAME>x</NAME></BANKALLOCATIONS.LIST>"
        b"</ALLLEDGERENTRIES.LIST></VOUCHER></COLLECTION></DATA></BODY></ENVELOPE>"
    )
    assert export.list_paths(body) == {"ALLLEDGERENTRIES", "ALLLEDGERENTRIES.BANKALLOCATIONS"}
    connector = export.connector_list_paths()
    assert "ALLINVENTORYENTRIES.ACCOUNTINGALLOCATIONS.CATEGORYALLOCATIONS" in connector
    assert "INVENTORYENTRIESIN.BATCHALLOCATIONS" in connector


def test_status_comes_from_the_connector() -> None:
    assert inventory.status("GROUP", "RESERVEDNAME", attribute=True) == "column"
    assert inventory.status("LEDGER", "RESERVEDNAME", attribute=True) == "raw only"
    assert inventory.status("VOUCHER", "ALLLEDGERENTRIES.LIST/AMOUNT") == "column"
    path = "ALLLEDGERENTRIES.LIST/BANKALLOCATIONS.LIST/INSTRUMENTDATE"
    assert inventory.status("VOUCHER", path) == "extra"
    assert inventory.status("VOUCHER", "ALLLEDGERENTRIES.LIST/BILLALLOCATIONS.LIST/BILLDATE") == (
        "not fetched"
    )
    assert inventory.status("CURRENCY", "DECIMALSYMBOL") == "extra"  # read whole
    assert inventory.status("TAXUNIT", "NAME") == "not fetched"


def test_the_recording_is_complete() -> None:
    """Every field Tally's own Day Book export sets is in the recorded vouchers."""
    assert inventory.completeness_problems(export.DEFAULT_OUT) == []
    fields = inventory.inventory(export.DEFAULT_OUT)
    assert fields["VOUCHER"].objects == 79
    assert fields["COMPANY"].objects == 1
    # Fields the connector fetches by name that aren't part of an exported object.
    assert "MASTERID" in inventory.computed_on_request("LEDGER", fields["LEDGER"])


def test_the_field_list_is_up_to_date() -> None:
    fields = inventory.inventory(export.DEFAULT_OUT)
    expected = inventory.markdown(fields) + "\n"
    assert inventory.DOC.read_text("utf-8") == expected, (
        "out of date; run python -m devtools.tally_field_inventory"
    )
