import pytest

from connectors.tally import envelopes, parser
from connectors.tally.client import TallyError, decode_response
from tests.conftest import FIXTURES

SYNTHETIC = FIXTURES / "tally_synthetic"


def test_decode_utf16_with_and_without_bom() -> None:
    text = "<ENVELOPE>₹</ENVELOPE>"
    assert decode_response(text.encode("utf-16")) == text
    assert decode_response(text.encode("utf-16-le")) == text
    assert decode_response(text.encode("utf-8")) == text


def test_sanitize_removes_invalid_character_references_only() -> None:
    assert parser.sanitize("A&#4;B&#x1F;C&#38;D\x07E") == "ABC&#38;DE"


def test_parse_companies() -> None:
    (company,) = parser.parse_companies((SYNTHETIC / "companies.xml").read_bytes())
    assert company.name == "Synthetic Test Co"
    assert company.key == "11111111-aaaa-bbbb-cccc-000000000001"
    assert company.books_from is not None and company.books_from.isoformat() == "2024-04-01"
    assert company.books_to is not None and company.books_to.isoformat() == "2024-05-31"


def test_parse_records_keeps_keys_and_payload() -> None:
    body = (SYNTHETIC / "vouchers_2024-04.xml").read_bytes()
    records = list(parser.parse_records(body, envelopes.VOUCHERS, "entity-guid"))
    assert [r.source_key for r in records] == [
        "11111111-aaaa-bbbb-cccc-000000000401",
        "11111111-aaaa-bbbb-cccc-000000000402",
    ]
    assert [r.source_alter_id for r in records] == [20, 21]
    first = records[0]
    assert first.object_type == "voucher"
    assert first.source_entity_key == "entity-guid"
    assert first.payload.startswith("<VOUCHER ")
    assert first.payload.endswith("</VOUCHER>")
    assert "<AMOUNT>-1000.00</AMOUNT>" in first.payload
    assert "&#4;" not in first.payload


def test_utf16_response_parses_like_utf8() -> None:
    body = (SYNTHETIC / "ledgers.xml").read_text(encoding="utf-8").encode("utf-16")
    records = list(parser.parse_records(body, envelopes.LEDGERS, "e"))
    assert len(records) == 3


@pytest.mark.parametrize(
    "body",
    [
        b"<RESPONSE>Unknown Request, cannot be processed</RESPONSE>",
        b"<ENVELOPE><BODY><DATA><LINEERROR>Could not set SVCurrentCompany</LINEERROR>"
        b"</DATA></BODY></ENVELOPE>",
        b"<ENVELOPE><unclosed></ENVELOPE>",
    ],
)
def test_tally_errors_raise(body: bytes) -> None:
    with pytest.raises(TallyError):
        parser.parse_response(body)


def test_cmpinfo_counts_are_not_objects() -> None:
    # Shape of a real TallyPrime answer for a month without vouchers.
    body = (
        b"<ENVELOPE><HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER><BODY><DESC>"
        b"<CMPINFO><LEDGER>0</LEDGER><VOUCHER>0</VOUCHER></CMPINFO></DESC>"
        b"<DATA><COLLECTION></COLLECTION></DATA></BODY></ENVELOPE>"
    )
    assert parser.objects(parser.parse_response(body), "VOUCHER") == []
    assert list(parser.parse_records(body, envelopes.VOUCHERS, "e")) == []


def test_object_without_guid_raises() -> None:
    body = (
        b"<ENVELOPE><COLLECTION><LEDGER NAME='x'><ALTERID>1</ALTERID></LEDGER>"
        b"</COLLECTION></ENVELOPE>"
    )
    with pytest.raises(TallyError, match="without GUID"):
        list(parser.parse_records(body, envelopes.LEDGERS, "e"))
