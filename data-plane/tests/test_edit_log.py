"""TallyPrime Edit Log (2026-10-19): an alteration leaves no history in the XML export
(the audit lists stay empty); UPDATEDDATETIME records the current version's source time.
Recorded from the test company: the journal EDITLOG-ALTER-1, created and altered (31 to 37)."""

from datetime import datetime
from decimal import Decimal

import pytest

from connectors.tally import envelopes, mapping, parser
from connectors.tally.connector import TallyConnector
from tests.conftest import FIXTURES

EDIT_LOG = FIXTURES / "tally" / "rules" / "edit_log"


def _voucher(name: str):  # noqa: ANN202
    (voucher,) = parser.objects(parser.parse_response((EDIT_LOG / name).read_bytes()), "VOUCHER")
    return voucher


def test_an_altered_voucher_maps_to_its_current_version() -> None:
    voucher = _voucher("voucher_altered.xml")
    mapped = mapping.voucher(voucher, parser.source_key(voucher))
    lines = mapped.lines
    assert [(line.ledger_name, line.amount) for line in lines] == [
        ("Rent", Decimal("37.00")),
        ("Salary Payable", Decimal("-37.00")),
    ]
    assert mapped.source_altered_at is None


def test_updated_datetime_maps_to_a_naive_source_wall_clock() -> None:
    full = _voucher("voucher_altered_full.xml")
    mapped = mapping.voucher(full, parser.source_key(full))
    assert mapped.source_altered_at == datetime(2026, 10, 19, 9, 53, 21)


@pytest.mark.parametrize(
    "value",
    [None, "", "   ", "000000000", "20261319095321000", "20261019095321", "x" * 17],
)
def test_tally_datetime_returns_none_for_blank_or_invalid_values(value: str | None) -> None:
    assert parser.tally_datetime(value) is None


def test_tally_datetime_preserves_milliseconds() -> None:
    assert parser.tally_datetime("20261019095321123") == datetime(2026, 10, 19, 9, 53, 21, 123000)


def test_the_edit_history_isnt_in_the_export() -> None:
    """The full export keeps its audit lists empty after an alteration: no earlier version
    of a line appears anywhere, so nothing outside the lists read is counted."""
    full = _voucher("voucher_altered_full.xml")
    for tag in ("AUDITENTRIES.LIST", "ACCOUNTAUDITENTRIES.LIST", "OLDAUDITENTRIES.LIST"):
        for element in full.iter(tag):
            assert not any((e.text or "").strip() for e in element.iter()), tag
    assert [(e.text or "").strip() for e in full.iter("OLDAUDITENTRYIDS")] == ["-1"] * len(
        list(full.iter("OLDAUDITENTRYIDS"))
    )
    text = (EDIT_LOG / "voucher_altered_full.xml").read_text(encoding="utf-8")
    assert TallyConnector.unread_postings(text) == []
    assert (full.findtext("UPDATEDDATETIME") or "").strip() not in ("", "000000000")


def test_the_sync_fetches_the_edit_time() -> None:
    assert "UPDATEDDATETIME" in envelopes.VOUCHERS.fetch
    assert _voucher("voucher_altered.xml").findtext("UPDATEDDATETIME") is None
