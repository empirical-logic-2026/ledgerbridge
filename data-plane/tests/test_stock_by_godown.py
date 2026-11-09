"""Stock by godown and batch (data completion, part 3), on the seeded test company's
recordings of 2026-11-06 (tests/fixtures/tally/rules/data-completion): Gizmo's opening split
across two godowns, Gizmo Pro's across two godowns and two batches, a stock journal moving
Gizmo to "Branch Store" (STK-1), and Steel Sheet sent to a job worker and partly returned
(MAT-OUT-1, MAT-IN-2)."""

from decimal import Decimal

from connectors.tally import mapping, parser
from core.canonical import CanonicalInventoryLine, CanonicalOpeningBatch
from tests.conftest import FIXTURES

RULES = FIXTURES / "tally" / "rules" / "data-completion"


def _item(name: str):  # noqa: ANN202
    body = (RULES / "stock_items.xml").read_bytes()
    for element in parser.objects(parser.parse_response(body), "STOCKITEM"):
        if parser.object_name(element) == name:
            return mapping.stock_item(element, parser.source_key(element))
    raise AssertionError(f"{name} not recorded")


def _inventory(file: str, marker: str) -> tuple[CanonicalInventoryLine, ...]:
    body = (RULES / file).read_bytes()
    for element in parser.objects(parser.parse_response(body), "VOUCHER"):
        if f"[lb-seed:{marker}]" in (element.findtext("NARRATION") or ""):
            return mapping.voucher(element, parser.source_key(element)).inventory
    raise AssertionError(f"{marker} not recorded")


def test_an_items_opening_by_godown_adds_up_to_its_opening() -> None:
    item = _item("Gizmo")
    assert item.opening_batches == (
        CanonicalOpeningBatch("Main Location", "Primary Batch", Decimal(20), Decimal(20),
                              Decimal(400)),
        CanonicalOpeningBatch("Branch Store", "Primary Batch", Decimal(10), Decimal(20),
                              Decimal(200)),
    )  # fmt: skip
    assert sum(b.quantity for b in item.opening_batches) == item.opening_qty == 30
    assert sum(b.value for b in item.opening_batches) == item.opening_value == 600


def test_a_batch_wise_items_opening_keeps_its_batches() -> None:
    item = _item("Gizmo Pro")
    assert [(b.godown_name, b.batch_name, b.quantity, b.value) for b in item.opening_batches] == [
        ("Main Location", "Batch A", Decimal(8), Decimal(240)),
        ("Branch Store", "Batch B", Decimal(4), Decimal(120)),
    ]


def test_an_item_without_an_opening_has_no_batches() -> None:
    """Tally lists an empty allocation for such an item: it isn't an opening."""
    body = (RULES / "stock_items.xml").read_bytes()
    items = [
        mapping.stock_item(e, parser.source_key(e))
        for e in parser.objects(parser.parse_response(body), "STOCKITEM")
    ]
    without = [i for i in items if not i.opening_qty and not i.opening_value]
    assert without and all(i.opening_batches == () for i in without)


def test_a_transfer_between_godowns_links_both_lines() -> None:
    """STK-1: the voucher names the receiving godown; the line leaving gets it, the line
    arriving gets the godown it left."""
    lines = _inventory("vouchers_2026-10.xml", "STK-1")
    moves = {(x.godown_name, x.quantity, x.counterpart_godown_name) for x in lines}
    assert moves == {
        ("Main Location", Decimal(-5), "Branch Store"),
        ("Branch Store", Decimal(5), "Main Location"),
    }


def test_a_manufacturing_journals_destination_is_not_the_components() -> None:
    """SJ-MFG-1 names Main Location as its destination: where the product goes. The
    component consumed (another item) has no counterpart godown."""
    lines = _inventory("vouchers_2026-09.xml", "SJ-MFG-1")
    assert lines and all(x.counterpart_godown_name is None for x in lines)


def test_material_sent_to_a_job_worker_names_where_it_goes() -> None:
    (line,) = _inventory("vouchers_2026-08.xml", "MAT-OUT-1")
    assert (line.item_name, line.godown_name, line.quantity) == (
        "Steel Sheet",
        "Main Location",
        Decimal(-80),
    )
    assert line.counterpart_godown_name == "Job Worker Alpha"


def test_material_returned_from_a_job_worker_names_where_it_came_from() -> None:
    (line,) = _inventory("vouchers_2026-09.xml", "MAT-IN-2")
    assert (line.godown_name, line.quantity) == ("Main Location", Decimal(10))
    assert line.counterpart_godown_name == "Job Worker Alpha"


def test_material_received_without_a_godown_named_has_no_counterpart() -> None:
    (line,) = _inventory("vouchers_2026-08.xml", "MAT-IN-1")
    assert line.quantity > 0 and line.counterpart_godown_name is None
