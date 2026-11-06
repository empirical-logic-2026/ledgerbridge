"""Bank details and the UTR (data completion, part 1), on the seeded test company's recordings
of 2026-11-06 (tests/fixtures/tally/rules/data-completion): an NEFT whose UTR is only in the
narration (BANK-3), a cheque with its cleared date (BANK-4), an IMPS whose reference Tally keeps
in BANKTRANSACTIONREFERENCE (BANK-5). Also the fields never fetched, a connection's
user-defined fields and find-field."""

import re
from datetime import date

import pytest

from connectors.tally import envelopes, find_field, mapping, parser
from connectors.tally.connector import TallyConnector
from core.canonical import CanonicalLine
from tests.conftest import FIXTURES

RULES = FIXTURES / "tally" / "rules" / "data-completion"
OCTOBER = RULES / "vouchers_2026-10.xml"


def _bank_line(marker: str) -> CanonicalLine:
    for element in parser.objects(parser.parse_response(OCTOBER.read_bytes()), "VOUCHER"):
        if f"[lb-seed:{marker}]" in (element.findtext("NARRATION") or ""):
            voucher = mapping.voucher(element, parser.source_key(element))
            return next(line for line in voucher.lines if line.has_bank_details)
    raise AssertionError(f"{marker} not recorded")


def test_a_utr_only_in_the_narration_is_taken_from_it() -> None:
    line = _bank_line("BANK-3")
    assert (line.utr, line.utr_source) == ("HDFCN52026100112345", "narration")
    assert (line.instrument_number, line.transaction_type) == ("NEFT", "e-Fund Transfer")
    assert line.instrument_date == date(2026, 10, 1)
    assert line.bank_cleared_date is None and line.bank_recon_status == "Available Only in Books"


def test_a_cheque_keeps_its_dates_and_reconciliation() -> None:
    line = _bank_line("BANK-4")
    assert (line.instrument_number, line.transaction_type) == ("000777", "Cheque")
    assert (line.instrument_date, line.bank_cleared_date) == (date(2026, 10, 1), date(2026, 10, 2))
    assert line.bank_recon_status == "Reconciled"
    assert line.utr is None  # a cheque has no UTR, and its number is not one


def test_a_bank_reference_field_holds_the_utr() -> None:
    line = _bank_line("BANK-5")
    assert (line.utr, line.utr_source) == ("629012345678", "bank_field")
    assert line.instrument_number == "IMPS"


def test_tallys_own_reference_is_never_a_utr() -> None:
    body = OCTOBER.read_bytes().replace(
        b"<INSTRUMENTNUMBER>000777</INSTRUMENTNUMBER>",
        b"<INSTRUMENTNUMBER>000777</INSTRUMENTNUMBER>"
        b"<UNIQUEREFERENCENUMBER>HDFCN52026100199999</UNIQUEREFERENCENUMBER>",
    )
    for element in parser.objects(parser.parse_response(body), "VOUCHER"):
        if "[lb-seed:BANK-4]" in (element.findtext("NARRATION") or ""):
            line = next(x for x in mapping.voucher(element, "k").lines if x.has_bank_details)
            assert line.tally_bank_entry_id == "HDFCN52026100199999"
            assert line.utr is None


def test_a_user_defined_field_can_hold_the_utr() -> None:
    """Synthetic: the test company has no UDFs (they need a TDL in Tally)."""
    body = (
        OCTOBER.read_bytes()
        .replace(
            b'<NARRATION TYPE="String">Paid Iota by IMPS',
            b'<UDF:VCHUTR.LIST DESC="`VchUTR`" ISLIST="YES" TYPE="String" INDEX="1001">'
            b"<UDF:VCHUTR>SBINR52026100100001</UDF:VCHUTR></UDF:VCHUTR.LIST>"
            b'<NARRATION TYPE="String">Paid Iota by IMPS',
        )
        .replace(b"<BANKTRANSACTIONREFERENCE>629012345678</BANKTRANSACTIONREFERENCE>", b"")
    )
    for element in parser.objects(parser.parse_response(body), "VOUCHER"):
        if "[lb-seed:BANK-5]" in (element.findtext("NARRATION") or ""):
            line = next(x for x in mapping.voucher(element, "k").lines if x.has_bank_details)
            assert (line.utr, line.utr_source) == ("SBINR52026100100001", "udf")


def _specs() -> list[envelopes.CollectionSpec]:
    return [v for v in vars(envelopes).values() if isinstance(v, envelopes.CollectionSpec)]


def test_no_request_names_a_denied_field() -> None:
    for spec in _specs():
        assert not envelopes.denied_in(spec.fetch), spec.collection_id
    assert envelopes.denied_in(("AllLedgerEntries.BankAllocations.AccountNumber",))
    assert not set(envelopes.BANK_FIELDS) & {f.title() for f in envelopes.DENIED}


def test_a_connections_user_defined_fields_are_added_by_their_find_field_paths() -> None:
    spec = envelopes.with_udfs(
        envelopes.VOUCHERS,
        ("UDF:VCHUTR.LIST/UDF:VCHUTR", "ALLLEDGERENTRIES.LIST/UDF:LINEUTR.LIST/UDF:LINEUTR"),
    )
    assert spec.fetch[-2:] == ("VCHUTR", "AllLedgerEntries.LINEUTR")
    for bad in ("ACCOUNTNUMBER", "UDF:ACCOUNTNUMBER", "UDF:A B", "BANKALLOCATIONS.LIST/UDF:X"):
        with pytest.raises(ValueError):
            envelopes.with_udfs(envelopes.VOUCHERS, (bad,))
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000", "udf_fields": ["UDF:VCHUTR.LIST/UDF:VCHUTR"]}
    )
    assert connector.vouchers.fetch[-1] == "VCHUTR"
    assert connector._spec("voucher") is connector.vouchers


def test_find_field_asks_for_one_voucher_whole_and_gives_paths_only() -> None:
    asked: list[str] = []

    def post(request: str) -> bytes:
        asked.append(request)
        return OCTOBER.read_bytes()

    count, paths = find_field.find_field(
        post, "LedgerBridge Test Co", date(2026, 10, 2), "18", "62901"
    )
    assert '$VoucherNumber = "18"' in asked[0] and "<NATIVEMETHOD>*</NATIVEMETHOD>" in asked[0]
    assert "ALLLEDGERENTRIES.BANKALLOCATIONS.*" in asked[0]
    assert count > 0
    assert paths == ["ALLLEDGERENTRIES.LIST/BANKALLOCATIONS.LIST/BANKTRANSACTIONREFERENCE"]
    assert not any(re.search(r"\d{5}", p) for p in paths)  # paths, never values
    with pytest.raises(ValueError):
        find_field.find_field(post, "LedgerBridge Test Co", date(2026, 10, 2), "18", "ab")
    with pytest.raises(ValueError):
        find_field.whole_collection_request("Voucher", "X", voucher_number='1" OR "1')
