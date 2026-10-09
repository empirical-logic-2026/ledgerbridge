import re
import xml.etree.ElementTree as ET  # noqa: N817
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from connectors.tally.signs import tally_amount
from core.config import Settings
from devtools.tally_seed import requests as rq
from devtools.tally_seed.data import SEED, Entry, Voucher, expected_balances, validate
from devtools.tally_seed.seed import (
    ImportFailedError,
    ImportResult,
    SeedRefusedError,
    TallyState,
    VoucherState,
    check_guards,
    parse_import_response,
    seed,
)

COMPANY = "LedgerBridge Test Co"


def test_seed_data_is_valid() -> None:
    assert validate(SEED) == []


def test_validate_rejects_non_educational_dates_and_imbalance() -> None:
    bad = Voucher(
        "BAD",
        "Payment",
        date(2026, 4, 15),
        "x",
        (Entry("Rent", "Dr", Decimal("10")), Entry("Cash", "Cr", Decimal("9"))),
    )
    problems = validate(replace(SEED, vouchers=(bad,)))
    assert any("day 15" in p for p in problems)
    assert any("debits 10 != credits 9" in p for p in problems)


def test_expected_trial_balance_for_anchors() -> None:
    balances = expected_balances(SEED)
    assert balances["Rent"] == (Decimal("1000"), "Dr")  # cancelled 500 excluded
    assert balances["Cash"] == (Decimal("27500"), "Dr")  # contra, receipts, payments, altered 1,500
    assert balances["Capital"] == (Decimal("50000"), "Cr")
    assert balances["Test Bank Current A/c"] == (Decimal("19360"), "Dr")
    total = sum(a if s == "Dr" else -a for a, s in balances.values())
    assert total == 0


@pytest.mark.parametrize(
    ("env", "loaded", "message"),
    [
        ("pilot", [COMPANY], "APP_ENV"),
        ("test", [COMPANY, "Other Co"], "2 companies"),
        ("test", [], "0 companies"),
        ("test", ["ledgerbridge test co"], "does not exactly match"),
    ],
)
def test_guards_refuse(env: str, loaded: list[str], message: str) -> None:
    settings = Settings(_env_file=None, app_env=env, ai_provider="ollama")
    with pytest.raises(SeedRefusedError, match=message):
        check_guards(settings, COMPANY, loaded)


def test_guards_pass_for_exact_single_test_company() -> None:
    check_guards(Settings(_env_file=None), COMPANY, [COMPANY])


def test_debit_is_deemed_positive_with_negative_amount() -> None:
    root = ET.fromstring(rq.voucher_create(SEED.vouchers[0]))
    entries = {e.findtext("LEDGERNAME"): e for e in root.iter("ALLLEDGERENTRIES.LIST")}
    assert entries["Rent"].findtext("ISDEEMEDPOSITIVE") == "Yes"
    assert entries["Rent"].findtext("AMOUNT") == "-1000.00"
    assert entries["Cash"].findtext("ISDEEMEDPOSITIVE") == "No"
    assert entries["Cash"].findtext("AMOUNT") == "1000.00"
    assert "[lb-seed:PMT-ANCHOR]" in root.findtext("NARRATION")


def test_every_request_is_an_import_for_the_named_company() -> None:
    xml = rq.envelope(COMPANY, "Vouchers", rq.voucher_create(SEED.vouchers[1]))
    root = ET.fromstring(xml)
    assert root.findtext("HEADER/TALLYREQUEST") == "Import Data"
    assert root.findtext(".//SVCURRENTCOMPANY") == COMPANY
    assert root.find(".//ALLINVENTORYENTRIES.LIST/ACCOUNTINGALLOCATIONS.LIST") is not None


def test_parse_import_response_reads_counts_and_errors() -> None:
    ok = parse_import_response(
        b"<RESPONSE><CREATED>1</CREATED><ALTERED>0</ALTERED><ERRORS>0</ERRORS></RESPONSE>"
    )
    assert ok.ok and ok.created == 1
    bad = parse_import_response(
        b"<RESPONSE><CREATED>0</CREATED><ERRORS>1</ERRORS>"
        b"<LINEERROR>Voucher date is not allowed</LINEERROR></RESPONSE>"
    )
    assert not bad.ok and bad.messages == ["Voucher date is not allowed"]


class FakeTally:
    """Applies seed import requests to an in-memory TallyState."""

    def __init__(self, cost_centres_enabled: bool = True) -> None:
        self.state = TallyState(
            ledgers={"Cash": Decimal(0), "Profit & Loss A/c": Decimal(0)},
            units=set(),
            stock_items=set(),
            cost_centres=set(),
            cost_centres_enabled=cost_centres_enabled,
            vouchers={},
        )
        self.requests = 0
        self.next_id = 100

    def read(self) -> TallyState:
        return self.state

    def post(self, request_xml: str) -> ImportResult:
        self.requests += 1
        for obj in ET.fromstring(request_xml).find(".//TALLYMESSAGE"):
            action = obj.get("ACTION")
            if obj.tag == "UNIT":
                self.state.units.add(obj.get("NAME"))
            elif obj.tag == "STOCKITEM":
                self.state.stock_items.add(obj.get("NAME"))
            elif obj.tag == "COSTCENTRE":
                self.state.cost_centres.add(obj.get("NAME"))
            elif obj.tag == "LEDGER":
                self.state.ledgers[obj.get("NAME")] = tally_amount(obj.findtext("OPENINGBALANCE"))
            elif obj.tag == "VOUCHER":
                marker = re.search(r"\[lb-seed:([A-Z0-9-]+)\]", obj.findtext("NARRATION")).group(1)
                if action == "Cancel":
                    self.state.vouchers[marker].cancelled = True
                    continue
                amounts: dict[str, Decimal] = {}
                for tag in ("ALLLEDGERENTRIES.LIST", "LEDGERENTRIES.LIST"):
                    for e in obj.findall(tag):
                        amounts[e.findtext("LEDGERNAME")] = tally_amount(e.findtext("AMOUNT"))
                if action == "Alter":
                    self.state.vouchers[marker].amounts = amounts
                else:
                    self.next_id += 1
                    self.state.vouchers[marker] = VoucherState(self.next_id, False, amounts)
        return ImportResult(created=1)


def test_seed_creates_everything_then_second_run_changes_nothing() -> None:
    tally = FakeTally()
    first = seed(SEED, COMPANY, tally.read, tally, log=lambda _: None)
    assert first.created["vouchers"] == len(SEED.vouchers)
    assert first.created["ledgers"] == len(SEED.ledgers) - 1  # Cash is predefined
    assert "opening balance of Cash" in first.altered
    assert first.cancelled == ["CANCEL-1"]
    assert "voucher ALTER-1" in first.altered
    assert tally.state.ledgers["Cash"] == Decimal("-50000")
    assert tally.state.ledgers["Capital"] == Decimal("50000")

    requests_before = tally.requests
    second = seed(SEED, COMPANY, tally.read, tally, log=lambda _: None)
    assert second.created == {} and second.altered == [] and second.cancelled == []
    assert tally.requests == requests_before


def test_seed_skips_cost_centre_voucher_when_feature_is_off() -> None:
    tally = FakeTally(cost_centres_enabled=False)
    report = seed(SEED, COMPANY, tally.read, tally, log=lambda _: None)
    assert "CC-1" not in tally.state.vouchers
    assert any("cost centres" in s for s in report.skipped)
    assert any("CC-1" in s for s in report.skipped)


def test_rejected_import_stops_with_tallys_message() -> None:
    class Rejecting(FakeTally):
        def post(self, request_xml: str) -> ImportResult:
            return ImportResult(errors=1, messages=["Voucher date is not allowed"])

    tally = Rejecting()
    with pytest.raises(ImportFailedError, match="Voucher date is not allowed"):
        seed(SEED, COMPANY, tally.read, tally, log=lambda _: None)
