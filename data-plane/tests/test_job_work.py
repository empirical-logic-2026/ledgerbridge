"""Job work, godowns and the opening difference, as Tally counts them (checked on the test
company with job work enabled, 2026-10-15; schema.md 7.5, ADR-031):

- stock at a godown marked "our stock with third party" (a job worker's location) is left
  out of Tally's item balances, Stock Summary and closing stock value; stock at a
  "third-party stock with us" godown is counted;
- Material Out / Material In move stock at the line's godown (Main Location); the batch's
  destination godown (the job worker's) moves nothing in Tally's balances; consumption at
  the job worker's godown changes no total;
- Tally's difference in opening balances is its ledger openings plus opening stock value.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.tally import envelopes, mapping, parser
from connectors.tally.connector import TallyConnector, _canonical
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.raw_store import RawStore
from core.transform import Transformer
from core.validation import Validator
from devtools.tally_seed.data import SEED, expected_stock, expected_stock_by_godown
from tests.conftest import FIXTURES

RULES = FIXTURES / "tally" / "rules"
YEAR_END = date(2027, 3, 31)
JOB_WORK_ITEMS = ("Steel Sheet", "Bracket", "Client Fabric")


def _objects(name: str, spec: envelopes.CollectionSpec) -> list:
    return parser.objects(parser.parse_response((RULES / name).read_bytes()), spec.object_tag)


def test_godowns_say_whose_stock_they_hold() -> None:
    records = parser.parse_records((RULES / "godowns.xml").read_bytes(), envelopes.GODOWNS, "e")
    holdings = {godown.name: godown.holding for r in records for godown in mapping.to_canonical(r)}
    assert holdings == {
        "Main Location": "own",
        "Job Worker Alpha": "ours_with_third_party",
        "Principal Stock": "third_party_with_us",
    }


def _vouchers() -> dict[str, object]:
    out = {}
    for v in _objects("vouchers_job_work.xml", envelopes.VOUCHERS):
        marker = (v.findtext("NARRATION") or "").split("[lb-seed:")[-1].rstrip("]")
        out[marker] = mapping.voucher(v, "k")
    return out


def test_job_work_vouchers_map_to_the_lines_godown() -> None:
    v = _vouchers()
    (sent,) = v["MAT-OUT-1"].inventory
    assert (sent.quantity, sent.godown_name) == (Decimal(-80), "Main Location")
    (back,) = v["MAT-IN-2"].inventory
    assert (back.quantity, back.godown_name) == (Decimal(10), "Main Location")
    (consumed,) = v["JW-CONSUME-1"].inventory  # a stock journal's out list
    assert (consumed.quantity, consumed.godown_name) == (Decimal(-60), "Job Worker Alpha")
    # A stock journal: Tally lists its entries in ALLINVENTORYENTRIES and again in its in
    # and out lists; each counts once.
    made, used = v["SJ-MFG-1"].inventory
    assert (made.item_name, made.quantity) == ("Bracket", Decimal(1))
    assert (used.item_name, used.quantity) == ("Hinge", Decimal(-2))
    (received,) = v["JWIN-IN-1"].inventory
    assert (received.quantity, received.godown_name) == (Decimal(50), "Principal Stock")
    # Partly tracked lines: only the untracked part moves stock on the invoice.
    (bought,) = v["PUR-PART-1"].inventory
    assert (bought.quantity, bought.tracked_quantity) == (Decimal(40), Decimal(30))
    (sold,) = v["SAL-PART-1"].inventory
    assert (sold.quantity, sold.tracked_quantity) == (Decimal(-6), Decimal(-4))
    (returned,) = v["DBN-TRK-1"].inventory
    assert returned.tracked_quantity == returned.quantity == Decimal(-5)


def test_a_line_split_across_godowns_becomes_one_line_per_godown() -> None:
    import xml.etree.ElementTree as ET  # noqa: N817

    entry = ET.fromstring(
        "<ALLINVENTORYENTRIES.LIST><STOCKITEMNAME>Gadget</STOCKITEMNAME>"
        "<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE><ACTUALQTY> 10 Nos</ACTUALQTY>"
        "<AMOUNT>-500.00</AMOUNT>"
        "<BATCHALLOCATIONS.LIST><GODOWNNAME>Main Location</GODOWNNAME>"
        "<ACTUALQTY> 6 Nos</ACTUALQTY><AMOUNT>-300.00</AMOUNT>"
        "<TRACKINGNUMBER>RN-9</TRACKINGNUMBER></BATCHALLOCATIONS.LIST>"
        "<BATCHALLOCATIONS.LIST><GODOWNNAME>Job Worker Alpha</GODOWNNAME>"
        "<ACTUALQTY> 4 Nos</ACTUALQTY><AMOUNT>-200.00</AMOUNT>"
        "<TRACKINGNUMBER> Not Applicable</TRACKINGNUMBER></BATCHALLOCATIONS.LIST>"
        "</ALLINVENTORYENTRIES.LIST>"
    )
    lines = mapping._inventory_lines(entry, None)
    assert [(x.godown_name, x.quantity, x.amount, x.tracked_quantity) for x in lines] == [
        ("Main Location", Decimal(6), Decimal(300), Decimal(6)),
        ("Job Worker Alpha", Decimal(4), Decimal(200), Decimal(0)),
    ]


def test_tallys_godown_balances_match_the_seed() -> None:
    """Tally's batches of Steel Sheet by godown: 30 at Main Location (100 - 80 + 10) and
    -60 at the job worker's godown (only the consumption: the Material Out's destination
    moved nothing there)."""
    by_godown = {
        b.findtext("GODOWNNAME"): mapping.quantity(b.findtext("CLOSINGBALANCE"))[0]
        for b in _objects("batches_steel_sheet.xml", envelopes.BATCHES)
    }
    assert by_godown == {"Main Location": Decimal(30), "Job Worker Alpha": Decimal(-60)}
    seed = expected_stock_by_godown(SEED)
    assert seed[("Steel Sheet", "Main Location")] == by_godown["Main Location"]
    assert seed[("Steel Sheet", "Job Worker Alpha")] == by_godown["Job Worker Alpha"]


def test_tallys_item_balances_leave_out_the_job_workers_godown() -> None:
    closing = {
        parser.object_name(i): mapping.quantity(i.findtext("CLOSINGBALANCE"))[0]
        for i in _objects("stock_values_books_to_year_end.xml", envelopes.STOCK_VALUES)
    }
    expected = expected_stock(SEED)
    for item in (*JOB_WORK_ITEMS, "Gadget", "Widget", "Hinge"):
        assert closing[item] == expected[item], item
    assert closing["Steel Sheet"] == 30  # not 30 + the job worker's -60


def test_tallys_opening_difference_includes_opening_stock() -> None:
    """Tally's ledger openings (-2,010: Capital - Stock balances the opening stock) plus
    its opening stock value (2,010) total zero: Tally shows no difference."""
    ledgers = sum(
        (_canonical(x.findtext("OPENINGBALANCE"))
         for x in _objects("ledger_balances_books_to_year_end.xml", envelopes.LEDGER_BALANCES)),
        Decimal(0),
    )  # fmt: skip
    stock = sum(
        (_canonical(i.findtext("OPENINGVALUE"))
         for i in _objects("stock_values_books_to_year_end.xml", envelopes.STOCK_VALUES)),
        Decimal(0),
    )  # fmt: skip
    assert (ledgers, stock) == (Decimal(-2010), Decimal(2010))


@pytest.fixture
def job_work(db: Session, synced: S.Connection, connector: TallyConnector) -> Session:
    """The synced test company plus the recorded job work godowns, items and vouchers."""
    entity_key = db.scalar(select(A.EntitySource.source_entity_key))
    records = []
    for name, spec in (
        ("stock_groups.xml", envelopes.STOCK_GROUPS),
        ("godowns.xml", envelopes.GODOWNS),
        ("stock_items_job_work.xml", envelopes.STOCK_ITEMS),
        ("vouchers_job_work.xml", envelopes.VOUCHERS),
    ):
        records += list(parser.parse_records((RULES / name).read_bytes(), spec, entity_key))
    RawStore(db).add(records, synced.id)
    db.commit()
    result = Transformer(db, synced.id, connector).run()
    assert result.failed == 0, result
    return db


def test_stock_validation_matches_tally_for_job_work(job_work: Session, synced) -> None:  # noqa: ANN001
    db = job_work
    closing = {
        parser.source_key(i): mapping.quantity(i.findtext("CLOSINGBALANCE"))[0]
        for i in _objects("stock_values_books_to_year_end.xml", envelopes.STOCK_VALUES)
        if parser.object_name(i) in JOB_WORK_ITEMS
    }
    items = dict(
        db.execute(
            select(A.Item.source_key, A.Item.id).where(A.Item.name.in_(JOB_WORK_ITEMS))
        ).all()
    )
    assert set(items) == set(closing)
    entity_id = db.scalar(select(A.Item.entity_id).where(A.Item.name == "Steel Sheet"))
    validator = Validator(db, entity_id, YEAR_END, Decimal(0), synced.id)
    validator._stock_quantities(closing)
    differing = {
        f.object_id
        for f in validator.findings
        if f.check_code == "stock_quantity_mismatch"
        and f.object_id in {str(i) for i in items.values()}
    }
    assert differing == set()  # the consumption at the job worker's godown isn't counted
    holding = dict(db.execute(select(A.Godown.name, A.Godown.holding)).all())
    assert holding["Job Worker Alpha"] == "ours_with_third_party"


# --- the stock ledger (a renamed Stock-in-Hand group) -------------------------------------

STOCK_LEDGER = RULES / "stock_ledger"


def _replaying(companies: str | None = None) -> TallyConnector:
    """A connector answered by the responses recorded from the test company."""
    import httpx

    files = {
        "LBCompanies": "companies.xml",
        "LBGroups": "groups.xml",
        "LBLedgerBalances": "ledger_balances.xml",
        "LBStockValues": "stock_values.xml",
    }

    def answer(request: httpx.Request) -> httpx.Response:
        collection = request.content.decode().split("<ID>")[1].split("</ID>")[0]
        text = (STOCK_LEDGER / files[collection]).read_text(encoding="utf-8")
        if collection == "LBCompanies" and companies is not None:
            text = companies
        return httpx.Response(200, content=text.encode("utf-8"))

    return TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=httpx.MockTransport(answer)
    )


def _test_company(connector: TallyConnector):  # noqa: ANN202
    return next(e for e in connector.list_entities() if e.name == "LedgerBridge Test Co")


def test_an_integrated_company_leaves_its_stock_ledger_out_of_the_opening_difference() -> None:
    """Recorded from the test company (2026-10-15): the reserved Stock-in-Hand group renamed
    "Inventories" holds one ledger with a 1,500 opening; the items' opening stock is 2,010.
    Tally's trial balance from the books' beginning shows Opening Stock 2,010 and no stock
    ledger, and balances: its difference in opening balances is zero."""
    connector = _replaying()
    entity = _test_company(connector)
    balances = connector.closing_balances(entity, YEAR_END)
    assert balances.opening_difference == 0
    assert balances.opening_stock == Decimal(2010)
    stock_ledger = next(
        parser.source_key(x)
        for x in parser.objects(
            parser.parse_response((STOCK_LEDGER / "ledger_balances.xml").read_bytes()), "LEDGER"
        )
        if parser.object_name(x) == "Stock Ledger"
    )
    # The ledger itself keeps its own opening and balance (validated ledger by ledger).
    assert balances.ledger_openings[stock_ledger] == Decimal(1500)
    assert balances.ledgers[stock_ledger] == Decimal(1500)
    assert connector._stock_in_hand_groups(entity) == {"Inventories"}


def test_without_integration_the_stock_ledgers_are_the_stock() -> None:
    """Not integrated: Tally's stock is the Stock-in-Hand ledgers, and their openings are
    part of the opening difference (here -2,010 capital + 1,500 stock ledger)."""
    text = (STOCK_LEDGER / "companies.xml").read_text(encoding="utf-8")
    connector = _replaying(text.replace(">Yes</ISINTEGRATED>", ">No</ISINTEGRATED>"))
    balances = connector.closing_balances(_test_company(connector), YEAR_END)
    assert balances.opening_difference == Decimal(-510)
    assert (balances.opening_stock, balances.closing_stock) == (Decimal(1500), Decimal(1500))
