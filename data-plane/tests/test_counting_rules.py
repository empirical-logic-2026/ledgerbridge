"""Tally's counting rules, checked against Tally's own figures on the test company
(2026-10-14; schema.md 7.4) after the pilot's `validate analyse` (ledgers differing from the
first year end by their opening, stock items by their opening or by sales lines):

1. Openings: Tally computes a master's OPENINGBALANCE for the requested period (the balance
   at its start). Masters with openings are fetched for a period starting on the books-
   beginning date, so the opening is the master's own.
2. Stock moves once: a sales, purchase, debit or credit note line tracked to a delivery or
   receipt note doesn't move stock; the note does, whichever came first.
3. What counts in the books: optional, memorandum and reversing journal vouchers don't;
   custom types under Journal and post-dated vouchers (from their date) do.
"""

import xml.etree.ElementTree as ET  # noqa: N817
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.base import Chunk, SourceEntity, SourceRecord
from connectors.tally import envelopes, mapping
from connectors.tally.connector import TallyConnector
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.models.source import RawRecord
from core.raw_store import RawStore
from core.transform import Transformer
from core.validation import Validator
from devtools.tally_seed import requests as rq
from devtools.tally_seed.data import SEED, expected_balances, expected_stock

EMPTY = b"<ENVELOPE><BODY><DATA><COLLECTION></COLLECTION></DATA></BODY></ENVELOPE>"


# --- 1. openings as at the books' beginning -----------------------------------------------


def _requests(entity: SourceEntity) -> dict[str, str]:
    """The request each chunk and the opening-bills read send (object type -> XML)."""
    connector = TallyConnector.from_config({"url": "http://tally.test:9000"})
    sent: dict[str, str] = {}

    def capture(entity, build, timeout=None):  # noqa: ANN001, ANN202
        xml = build(entity.name)
        sent[xml.split("<ID>")[1].split("</ID>")[0]] = xml
        return EMPTY

    connector._company_post = capture  # type: ignore[method-assign]
    for spec in envelopes.MASTER_SPECS:
        connector.fetch_chunk(entity, Chunk(spec.object_type), {})
    connector.fetch_chunk(entity, Chunk("voucher", None), {"voucher": "10"})
    connector.bill_outstanding(entity)
    return sent


def test_masters_with_openings_are_fetched_as_at_the_books_beginning() -> None:
    entity = SourceEntity("guid-1", "Co", books_from=date(2020, 4, 1))
    sent = _requests(entity)
    books_start = '<SVFROMDATE TYPE="Date">20200401</SVFROMDATE>'
    for collection in ("LBLedgers", "LBStockItems", "LBLedgerOpeningBills"):
        assert books_start in sent[collection], collection
    for collection in ("LBGroups", "LBVoucherTypes", "LBUnits", "LBVouchers"):
        assert "SVFROMDATE" not in sent[collection], collection


def test_without_a_books_beginning_date_nothing_changes() -> None:
    sent = _requests(SourceEntity("guid-1", "Co", books_from=None))
    assert "SVFROMDATE" not in sent["LBLedgers"]


def test_opening_fields_follow_the_requested_period() -> None:
    """Recorded from the test company: the same ledger and item, fetched for a period
    starting on the books' beginning (the master's opening) and for one starting on
    1 August (the balance at that date). Only the first is the opening."""
    from tests.conftest import FIXTURES

    folder = FIXTURES / "tally" / "rules"
    for name, books, august in (
        ("Cash", "-50000.00", "-29000.00"),
        ("Test Bank Current A/c", "0.00", "-22360.00"),
    ):
        at_books = _ledger(folder / "ledgers_books_beginning.xml", name)
        at_august = _ledger(folder / "ledgers_from_2026-08-01.xml", name)
        assert (at_books, at_august) == (books, august), name
    gadget = _item(folder / "stock_items_books_beginning.xml", "Gadget")
    assert mapping.stock_item(gadget, "k").opening_qty == Decimal("20")
    # As at 1 October Tally's stock shows each movement once: Gadget 20 + the receipt
    # note's 30 (not the purchase tracked to it); Widget -10 sold, -5 delivered by DN-1
    # (not the sale tracked to it).
    october = folder / "stock_items_from_2026-10-01.xml"
    assert mapping.stock_item(_item(october, "Gadget"), "k").opening_qty == Decimal("50")
    assert mapping.stock_item(_item(october, "Widget"), "k").opening_qty == Decimal("-15")


def _ledger(path, name: str) -> str:  # noqa: ANN001
    root = ET.parse(path).getroot()
    for ledger in root.iter("LEDGER"):
        if ledger.get("NAME") == name:
            return (ledger.findtext("OPENINGBALANCE") or "").strip()
    raise AssertionError(name)


def _item(path, name: str) -> ET.Element:  # noqa: ANN001
    root = ET.parse(path).getroot()
    return next(i for i in root.iter("STOCKITEM") if i.get("NAME") == name)


# --- 2. stock moves once -------------------------------------------------------------------


def _entry(*batches: tuple[str, str]) -> ET.Element:
    xml = (
        "<ALLINVENTORYENTRIES.LIST><STOCKITEMNAME>Widget</STOCKITEMNAME>"
        "<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><ACTUALQTY> 5 Nos</ACTUALQTY>"
        "<AMOUNT>1000.00</AMOUNT>"
        + "".join(
            f"<BATCHALLOCATIONS.LIST><TRACKINGNUMBER>{t}</TRACKINGNUMBER>"
            f"<ACTUALQTY> {q} Nos</ACTUALQTY></BATCHALLOCATIONS.LIST>"
            for t, q in batches
        )
        + "</ALLINVENTORYENTRIES.LIST>"
    )
    return ET.fromstring(xml)


@pytest.mark.parametrize(
    ("batches", "tracked"),
    [
        ((), Decimal(0)),
        (((" Not Applicable", "5"),), Decimal(0)),
        ((("DN-1", "5"),), Decimal(-5)),  # outward: signed like the quantity
        ((("DN-1", "3"), (" Not Applicable", "2")), Decimal(-3)),  # partly tracked
    ],
)
def test_tracked_quantity(batches, tracked) -> None:  # noqa: ANN001
    line = mapping._inventory(_entry(*batches))
    assert line is not None and line.quantity == Decimal(-5)
    assert line.tracked_quantity == tracked


def test_recorded_tracked_vouchers_map_the_tracking() -> None:
    """Vouchers recorded from the test company (seeded): a delivery note and the invoice
    tracked to it carry the same tracking number; an untracked invoice has none."""
    from tests.conftest import FIXTURES

    root = ET.parse(FIXTURES / "tally" / "rules" / "vouchers_tracked.xml").getroot()
    lines = {}
    for v in root.iter("VOUCHER"):
        marker = (v.findtext("NARRATION") or "").split("[lb-seed:")[-1].rstrip("]")
        lines[marker] = mapping.voucher(v, "k").inventory
    assert lines["DN-1"][0].tracked_quantity == Decimal(-5)  # its own number
    assert lines["SAL-DN-1"][0].tracked_quantity == Decimal(-5)
    assert lines["PUR-RN-1"][0].tracked_quantity == Decimal(30)
    assert lines["SAL-ITEM"][0].tracked_quantity == Decimal(0)
    assert lines["CN-TRK-1"][0].tracked_quantity == Decimal(2)  # the rejection RI-1 moves it
    assert lines["RI-1"][0].tracked_quantity == Decimal(2)


def _deliver(db: Session, synced: S.Connection, key: str, payload: str) -> None:
    template = db.scalars(
        select(RawRecord).where(
            RawRecord.object_type == "voucher", RawRecord.payload.contains("[lb-seed:SAL-ITEM]")
        )
    ).first()
    RawStore(db).add(
        [SourceRecord(template.source_entity_key, "voucher", key, 99_000, "xml", payload)],
        synced.id,
    )
    db.commit()


def _tracked_copy(db: Session, voucher_type: str, marker: str) -> str:
    payload = db.scalars(
        select(RawRecord.payload).where(
            RawRecord.object_type == "voucher", RawRecord.payload.contains("[lb-seed:SAL-ITEM]")
        )
    ).first()
    assert "<BATCHALLOCATIONS.LIST>" in payload
    payload = payload.replace(
        "<BATCHALLOCATIONS.LIST>",
        "<BATCHALLOCATIONS.LIST><TRACKINGNUMBER>DN-9</TRACKINGNUMBER>",
    )
    payload = payload.replace("[lb-seed:SAL-ITEM]", f"[lb-seed:{marker}]")
    return payload.replace(
        "<VOUCHERTYPENAME>Sales</VOUCHERTYPENAME>",
        f"<VOUCHERTYPENAME>{voucher_type}</VOUCHERTYPENAME>",
    )


def test_tracked_invoice_lines_dont_move_stock_but_the_note_does(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    widget = db.scalar(select(A.Item).where(A.Item.name == "Widget"))
    before = _stock(db, widget.id)
    _deliver(db, synced, "tracked-sale", _tracked_copy(db, "Sales", "T-SALE"))
    _deliver(db, synced, "tracked-note", _tracked_copy(db, "Delivery Note", "T-NOTE"))
    result = Transformer(db, synced.id, connector).run()
    assert result.failed == 0
    rows = {
        v.source_key: line
        for v, line in db.execute(
            select(A.Voucher, A.InventoryLine).join(
                A.InventoryLine, A.InventoryLine.voucher_id == A.Voucher.id
            )
        )
    }
    sale, note = rows["tracked-sale"], rows["tracked-note"]
    assert sale.quantity == note.quantity == Decimal(-10)
    assert sale.stock_quantity == 0  # the note moves it
    assert note.stock_quantity == Decimal(-10)
    assert _stock(db, widget.id) == before - 10  # counted once
    # The stock check counts what moves stock: Tally's figure matches.
    entity_id = widget.entity_id
    validator = Validator(db, entity_id, date(2027, 3, 31), Decimal(0), synced.id)
    validator._stock_quantities({widget.source_key: Decimal(before - 10)})
    assert not [f for f in validator.findings if f.check_code == "stock_quantity_mismatch"]


def _stock(db: Session, item_id: int) -> Decimal:
    opening = db.scalar(select(A.Item.opening_qty).where(A.Item.id == item_id))
    moved = sum(
        db.scalars(
            select(A.InventoryLine.stock_quantity)
            .join(A.Voucher, A.Voucher.id == A.InventoryLine.voucher_id)
            .join(A.VoucherType, A.VoucherType.id == A.Voucher.voucher_type_id)
            .where(
                A.InventoryLine.item_id == item_id,
                A.Voucher.is_cancelled.is_(False),
                A.VoucherType.moves_stock.is_(True),
            )
        ),
        Decimal(0),
    )
    return Decimal(opening) + moved


# --- the seed reproduces each rule, with Tally's own figures -------------------------------


def test_seed_reproduces_tallys_figures() -> None:
    """Tally's balances and stock at 2027-03-31 after seeding (read on the test company,
    2026-10-14): only the note moves stock; optional, memorandum and reversing journal
    vouchers don't count; the custom journal type and the post-dated voucher do."""
    stock = expected_stock(SEED)
    # Widget: -10 sold, -5 and -3 delivered, +2 returned (RI-1), -4 delivered (DN-3) and -2
    # untracked of SAL-PART-1. Gadget: 20 + 30 (RN-1) + 30 (RN-3) + 10 untracked of
    # PUR-PART-1 - 5 (RO-1). Job work items: tests/test_job_work.py.
    assert (stock["Widget"], stock["Gadget"]) == (Decimal(-22), Decimal(85))
    balances = expected_balances(SEED)
    # 1,000 + ADJ 300 + PDC 75 + the effective-date journals 11 and 13; REV out
    assert balances["Rent"] == (Decimal("1399"), "Dr")
    assert balances["Salary"] == (Decimal("15000"), "Dr")  # optional 400 out
    assert balances["Salary Payable"] == (Decimal("15324"), "Cr")  # with the 11 and 13
    assert balances["Electricity"] == (Decimal("4500"), "Dr")  # memorandum 250 out
    assert balances["Cash"] == (Decimal("27425"), "Dr")
    # The invoices post (+1,500, +2,000, debit note -250), the notes don't.
    assert balances["Purchases"] == (Decimal("16250"), "Dr")
    assert balances["Security Deposit"] == (Decimal("12000"), "Dr")


def test_seed_requests_carry_tracking_flags_and_openings() -> None:
    by_marker = {v.marker: v for v in SEED.vouchers}
    sale = ET.fromstring(rq.voucher_create(by_marker["SAL-DN-1"]))
    assert sale.findtext(".//BATCHALLOCATIONS.LIST/TRACKINGNUMBER") == "DN-1"
    receipt = ET.fromstring(rq.voucher_create(by_marker["RN-1"]))
    assert receipt.findtext(".//ALLINVENTORYENTRIES.LIST/ISDEEMEDPOSITIVE") == "Yes"
    assert receipt.findtext("PARTYLEDGERNAME") == "Vendor Delta Supplies"
    assert ET.fromstring(rq.voucher_create(by_marker["OPT-JNL-1"])).findtext("ISOPTIONAL") == "Yes"
    assert ET.fromstring(rq.voucher_create(by_marker["PDC-1"])).findtext("ISPOSTDATED") == "Yes"
    gadget = next(i for i in SEED.stock_items if i.name == "Gadget")
    item = ET.fromstring(rq.stock_item_create(gadget))
    assert item.findtext("OPENINGBALANCE").strip() == "20 Nos"
    assert item.findtext("OPENINGVALUE") == "-1000.00"
    custom = ET.fromstring(rq.voucher_type_create("Adjustment Journal", "Journal"))
    assert custom.findtext("PARENT") == "Journal"


def test_a_ledgers_balance_follows_its_opening_not_its_opening_bills() -> None:
    """Recorded from the test company (2026-10-15): a bill-wise ledger with an opening of
    1,000 Dr and opening bills totalling 1,200 Dr. Tally keeps the ledger's own opening, and
    its balance is that opening; only the bill-wise outstanding uses the bills."""
    from connectors.tally.connector import _canonical
    from tests.conftest import FIXTURES

    root = ET.parse(FIXTURES / "tally" / "rules" / "opening_bills_ledger.xml").getroot()
    balances, bills = root.findall(".//LEDGER")
    assert _canonical(balances.findtext("OPENINGBALANCE")) == Decimal(1000)
    assert _canonical(balances.findtext("CLOSINGBALANCE")) == Decimal(1000)
    total = sum(
        (_canonical(b.findtext("OPENINGBALANCE")) for b in bills.findall("BILLALLOCATIONS.LIST")),
        Decimal(0),
    )
    assert total == Decimal(1200)
