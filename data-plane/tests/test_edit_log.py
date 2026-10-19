"""TallyPrime Edit Log (2026-10-19): the test company opened in Edit Log exports the same
data in the same formats as TallyPrime did. An alteration leaves no history in the XML
export (the audit lists stay empty); only UPDATEDDATETIME is now filled, a field the sync
doesn't fetch, so stored records and their hashes don't change. Recorded from the test
company: the journal EDITLOG-ALTER-1, created and altered (31 to 37) under Edit Log."""

from decimal import Decimal

from connectors.tally import envelopes, mapping, parser
from connectors.tally.connector import TallyConnector
from tests.conftest import FIXTURES

EDIT_LOG = FIXTURES / "tally" / "rules" / "edit_log"


def _voucher(name: str):  # noqa: ANN202
    (voucher,) = parser.objects(parser.parse_response((EDIT_LOG / name).read_bytes()), "VOUCHER")
    return voucher


def test_an_altered_voucher_maps_to_its_current_version() -> None:
    voucher = _voucher("voucher_altered.xml")
    lines = mapping.voucher(voucher, parser.source_key(voucher)).lines
    assert [(line.ledger_name, line.amount) for line in lines] == [
        ("Rent", Decimal("37.00")),
        ("Salary Payable", Decimal("-37.00")),
    ]


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


def test_the_sync_doesnt_fetch_the_edit_time() -> None:
    """UPDATEDDATETIME changes with every edit under Edit Log; fetching it would store a
    voucher again whenever it is touched. The sync's own request leaves it out."""
    assert "UPDATEDDATETIME" not in envelopes.VOUCHERS.fetch
    assert _voucher("voucher_altered.xml").findtext("UPDATEDDATETIME") is None
