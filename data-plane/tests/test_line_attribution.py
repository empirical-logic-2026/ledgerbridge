"""Which ledger a voucher line belongs to (ADR-034; pilot 2026-10-16: three customers
differed while their vouchers matched, as if some lines sat on the wrong ledger).

1. Tally's names: trimmed, spaces collapsed and case ignored, one ledger per name or
   alias; a voucher naming an alias is stored under the ledger's name. Rows deleted in the
   source never take a live ledger's name.
2. Ledger lines in lists the mapping doesn't read are found (counts by list, never names).
"""

import xml.etree.ElementTree as ET  # noqa: N817
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.tally import mapping, parser
from connectors.tally.connector import TallyConnector
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.names import EXACT, NameIndex
from core.transform import Transformer
from tests.conftest import FIXTURES

VOUCHERS = FIXTURES / "tally" / "vouchers_2026-05.xml"


def _voucher() -> ET.Element:
    root = parser.parse_response(VOUCHERS.read_bytes())
    return next(v for v in parser.objects(root, "VOUCHER") if v.findall("ALLLEDGERENTRIES.LIST"))


def _payload(voucher: ET.Element, extra: str = "") -> str:
    text = ET.tostring(voucher, encoding="unicode")
    if extra:
        text = text.replace("</VOUCHER>", extra + "</VOUCHER>")
    return f"<ENVELOPE><BODY><DATA><COLLECTION>{text}</COLLECTION></DATA></BODY></ENVELOPE>"


def test_names_tally_treats_as_one_find_the_one_ledger() -> None:
    """On the test company (2026-10-16), Tally took "Party Lima ", "PARTY LIMA" and
    "Party  Lima" for the existing "Party Lima" (trimmed, spaces collapsed, case ignored),
    and refused a ledger whose alias was another ledger's name: a name identifies one
    ledger. The normalised match finds that one ledger, as Tally does."""
    index = NameIndex.build([("Party Lima", 1), ("Party Kilo", 2)], [("Kilo Alias", 2)])
    for written in ("Party Lima ", "PARTY LIMA", "Party  Lima"):
        assert index.resolve(written).value == 1, written
    assert index.resolve("Party Lima").how == EXACT
    assert index.resolve("kilo alias").value == 2


def test_the_lines_read_are_not_reported() -> None:
    assert TallyConnector.unread_postings(_payload(_voucher())) == []


def test_ledger_lines_in_lists_not_read_are_found() -> None:
    voucher = _voucher()
    read = voucher.find("ALLLEDGERENTRIES.LIST")
    assert read is not None
    same = (
        f"<LEDGERENTRIES.LIST><LEDGERNAME>{read.findtext('LEDGERNAME')}</LEDGERNAME>"
        f"<AMOUNT>{read.findtext('AMOUNT')}</AMOUNT></LEDGERENTRIES.LIST>"
    )  # the same line again: already read
    other = (
        "<LEDGERENTRIES.LIST><LEDGERNAME>Customer Beta Retail</LEDGERNAME>"
        "<AMOUNT>-50.00</AMOUNT></LEDGERENTRIES.LIST>"
    )
    custom = (
        "<UDF:EXTRAENTRIES.LIST><LEDGERNAME>Customer Beta Retail</LEDGERNAME>"
        "<AMOUNT>-60.00</AMOUNT></UDF:EXTRAENTRIES.LIST>"
    )
    found = TallyConnector.unread_postings(_payload(voucher, same + other + custom))
    assert sorted(found) == [
        ("LEDGERENTRIES.LIST", "Customer Beta Retail", Decimal("50.00")),
        ("a custom (prefixed) list", "Customer Beta Retail", Decimal("60.00")),
    ]


def test_a_deleted_ledger_never_takes_the_name_of_a_live_one(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    """Tally refuses vouchers on a deleted ledger, and one deleted and created again keeps
    its name: the live ledger is meant. A deleted twin read after it used to take the exact
    match (and make alias and normalised matches ambiguous)."""
    cash = db.scalars(select(A.Ledger).where(A.Ledger.name == "Cash")).one()
    copy = {
        c.name: getattr(cash, c.key) for c in A.Ledger.__table__.columns if c.name not in ("id",)
    }
    db.add(A.Ledger(**{**copy, "source_key": "deleted-twin", "is_deleted": True}))
    db.commit()
    transformer = Transformer(db, synced.id, connector)
    transformer.entity_id = cash.entity_id
    index = transformer._by_name(A.Ledger, "name", "party_id", "tax_type")
    for written in ("Cash", "CASH ", "Cash"):
        assert index.resolve(written).value[0] == cash.id, written


def test_tally_stores_a_voucher_naming_an_alias_under_the_ledgers_name() -> None:
    """Recorded from the test company: a journal imported naming "Kilo Alias" comes back
    naming "Party Kilo"; "Party Lima" keeps its own name, the last name given ("Party  Lima",
    which Tally took for it) only in its name list."""
    folder = FIXTURES / "tally" / "rules" / "names"
    ledgers = parser.objects(parser.parse_response((folder / "ledgers.xml").read_bytes()), "LEDGER")
    by_name = {
        r.name: r
        for x in ledgers
        for r in mapping.ledger(x, parser.source_key(x), "e")
        if getattr(r, "aliases", None) is not None
    }
    assert by_name["Party Kilo"].aliases == ("Kilo Alias",)
    assert by_name["Party Lima"].aliases == ("Party  Lima",)
    index = NameIndex.build(
        [(n, n) for n in by_name], [(a, n) for n, r in by_name.items() for a in r.aliases]
    )
    root = parser.parse_response((folder / "vouchers.xml").read_bytes())
    (voucher,) = parser.objects(root, "VOUCHER")
    names = [line.ledger_name for line in mapping.voucher(voucher, "k").lines]
    assert "Party Kilo" in names and "Kilo Alias" not in names
    assert index.resolve("Party Kilo").how == EXACT
