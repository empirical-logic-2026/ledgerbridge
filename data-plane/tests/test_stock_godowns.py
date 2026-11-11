"""Stock by godown and batch (core/stock_godowns.py; F-STK-010 to F-STK-013), proved against
Tally's own reports on the test company at 02-Oct-2026 (tests/fixtures/tally/rules/
stock_values: its books with an own godown, a job worker's godown and a godown holding
others' stock, and Tally's Stock Summary, Godown Summary and item balances recorded the
same day).

What Tally does (the recordings):
- Stock Summary and item balances: Steel Sheet 30 (Main Location's 30; the job worker's
  -60 is not in it), Client Fabric 30 valued 120 (all of it at Principal Stock, others'
  stock held with us: in it), total value 5,580.
- Godown Summary: Main Location 127 (5,460), Principal Stock 30 (120), Job Worker Alpha -60
  (no value). 127 + 30 = 157 = the item balances' total; 5,460 + 120 = 5,580.
So the page's total is our stock plus others' stock held with us; our stock at job workers
is shown apart, outside it.
"""

import re
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from connectors.tally import envelopes, mapping, parser
from core import statements
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.report_periods import Period
from core.stock import find_item, item_page, stock_summary
from core.stock_godowns import IN_TOTAL, by_godown
from tests.stock_replay import FOLDER
from tests.test_statements import _source, _synced, books  # noqa: F401  (a fixture)

AS_OF = date(2026, 10, 2)
PERIOD = Period(date(2026, 4, 1), AS_OF)
TALLY = FOLDER / "integrated"
D = Decimal


def _tally(name: str, spec: envelopes.CollectionSpec) -> dict[str, tuple[Decimal, Decimal]]:
    """Name -> (closing quantity, closing value) as Tally reports them (value a debit)."""
    found = {}
    for o in parser.objects(parser.parse_response((TALLY / name).read_bytes()), spec.object_tag):
        quantity = mapping.quantity(o.findtext("CLOSINGBALANCE"))[0] or D(0)
        value = -D(o.findtext("CLOSINGVALUE") or "0")  # Tally: a debit is negative
        found[parser.object_name(o)] = (quantity, value)
    return found


def _stock_summary_value() -> Decimal:
    """The total of the closing values in Tally's Stock Summary report."""
    text = (TALLY / "stock_summary_2026-10-02.xml").read_text("utf-8", errors="replace")
    return -sum((D(v) for v in re.findall(r"<DSPCLAMTA>([^<]+)</DSPCLAMTA>", text)), D(0))


@pytest.fixture
def stored(db: Session, books: S.Connection) -> list[int]:  # noqa: F811
    """The test company with Tally's statements and stock values stored at 02-Oct-2026."""
    entity_id = db.query(A.Entity).one().id
    statements.refresh(db, entity_id, books.id, "live", _source("integrated", AS_OF))
    return [entity_id]


def test_the_page_total_equals_tallys_stock_summary(db: Session, stored: list[int]) -> None:
    items = _tally("stock_value_2026-10-02.xml", envelopes.STOCK_VALUES)
    found = by_godown(db, stored, PERIOD)
    quantity, value = found.counted()
    assert quantity == sum(q for q, _ in items.values()) == D(157)
    assert value == _stock_summary_value() == D(5580)


def test_our_stock_at_a_job_worker_is_apart_and_outside_the_total(
    db: Session, stored: list[int]
) -> None:
    """Tally's Godown Summary: Job Worker Alpha -60, no value; its Stock Summary leaves it
    out (Steel Sheet 30, not -30)."""
    godowns = _tally("godown_value_2026-10-02.xml", envelopes.GODOWN_VALUES)
    found = by_godown(db, stored, PERIOD)
    rows = [r for r in found.rows if r.section == "at_job_workers"]
    assert {r.godown for r in rows} == {"Job Worker Alpha"}
    assert found.total("at_job_workers") == (godowns["Job Worker Alpha"][0], None) == (D(-60), None)
    assert "at_job_workers" not in IN_TOTAL
    steel = sum(r.quantity for r in found.rows if r.item == "Steel Sheet" and r.section in IN_TOTAL)
    assert steel == _tally("stock_value_2026-10-02.xml", envelopes.STOCK_VALUES)["Steel Sheet"][0]


def test_others_stock_held_with_us_is_apart_but_in_the_total(
    db: Session, stored: list[int]
) -> None:
    """Tally's Godown Summary: Principal Stock 30 valued 120; its Stock Summary counts
    Client Fabric (all at Principal Stock) at 30 and 120."""
    godowns = _tally("godown_value_2026-10-02.xml", envelopes.GODOWN_VALUES)
    found = by_godown(db, stored, PERIOD)
    assert {r.godown for r in found.rows if r.section == "held_for_others"} == {"Principal Stock"}
    assert found.total("held_for_others") == godowns["Principal Stock"] == (D(30), D(120))
    assert "held_for_others" in IN_TOTAL
    assert found.total("ours") == godowns["Main Location"] == (D(127), D(5460))


def test_each_items_godowns_add_up_to_its_stock_page_figures(
    db: Session, stored: list[int]
) -> None:
    summary = {r.name: r for r in stock_summary(db, stored, PERIOD).items}
    found = by_godown(db, stored, PERIOD)
    for name, item in summary.items():
        rows = [r for r in found.rows if r.item == name and r.section in IN_TOTAL]
        assert sum((r.quantity for r in rows), D(0)) == item.closing, name
        values = [r.value for r in rows if r.value is not None]
        if item.value is not None and item.closing != 0:
            assert sum(values, D(0)) == item.value, name  # the remainder keeps it exact
    assert all(r.value is None for r in found.rows if r.section == "at_job_workers")


def test_only_the_named_items(db: Session, stored: list[int]) -> None:
    """This recording predates the openings by godown (data completion part 3): Steel
    Sheet's opening of 100 is a row without a godown, still in the total."""
    found = by_godown(db, stored, PERIOD, {"Steel Sheet"})
    assert {r.item for r in found.rows} == {"Steel Sheet"}
    assert {(r.section, r.godown) for r in found.rows} == {
        ("ours", None), ("ours", "Main Location"), ("at_job_workers", "Job Worker Alpha"),
    }  # fmt: skip
    opening = next(r for r in found.rows if r.godown is None)
    assert opening.quantity == D(100)


# --- the seeded data-completion recording: openings by godown and batch, a transfer ---------

DATA_COMPLETION = FOLDER.parent / "data-completion"


@pytest.fixture
def completed(db: Session, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The test company's recording of 2026-11-06 (data completion), synced."""
    _synced(db, monkeypatch, DATA_COMPLETION)
    return [db.query(A.Entity).one().id]


@pytest.mark.parametrize("end", [date(2026, 4, 30), date(2026, 9, 30), date(2026, 10, 31)])
def test_godowns_and_batches_add_up_to_each_items_closing(
    db: Session, completed: list[int], end: date
) -> None:
    period = Period(date(2026, 4, 1), end)
    summary = {r.name: r.closing for r in stock_summary(db, completed, period).items}
    found = by_godown(db, completed, period)
    totals: dict[str, Decimal] = {}
    for r in found.rows:
        if r.section in IN_TOTAL:
            totals[r.item] = totals.get(r.item, D(0)) + r.quantity
    assert {k: v for k, v in totals.items() if v} == {k: v for k, v in summary.items() if v}


def test_openings_by_godown_and_batch_and_a_transfer_show_where_the_stock_is(
    db: Session, completed: list[int]
) -> None:
    found = by_godown(db, completed, Period(date(2026, 4, 1), date(2026, 10, 31)))
    gizmo = {(r.godown, r.batch) for r in found.rows if r.item == "Gizmo"}
    assert "Branch Store" in {g for g, _ in gizmo}  # STK-1 moved some there
    assert len({g for g, _ in gizmo}) >= 2
    pro = {(r.godown, r.batch) for r in found.rows if r.item == "Gizmo Pro"}
    assert len({b for _, b in pro if b}) >= 2  # its batches stay apart


def _page(db: Session, companies: list[int], name: str, godown: str | None = None):  # noqa: ANN202
    item_id = db.query(A.Item).filter(A.Item.name == name).one().id
    ref = find_item(db, companies, item_id)
    assert ref is not None
    return item_page(db, companies, ref, Period(date(2026, 4, 1), date(2026, 10, 31)), godown)


def test_an_items_movements_name_the_other_godown(db: Session, completed: list[int]) -> None:
    page = _page(db, completed, "Gizmo")
    moves = [(m.godown, m.other_godown) for m in page.movements if m.other_godown]
    assert ("Main Location", "Branch Store") in moves or ("Branch Store", "Main Location") in moves


def test_an_items_page_at_one_godown_shows_only_that_godown(
    db: Session, completed: list[int]
) -> None:
    whole = _page(db, completed, "Gizmo")
    at_branch = _page(db, completed, "Gizmo", "Branch Store")
    assert at_branch.godown == "Branch Store"
    assert at_branch.movements and {m.godown for m in at_branch.movements} == {"Branch Store"}
    branch_rows = [r for r in whole.by_godown if r.godown == "Branch Store"]
    assert at_branch.movements[-1].balance == sum((r.quantity for r in branch_rows), D(0))
    assert at_branch.months[-1].closing == at_branch.movements[-1].balance
    assert all(m.value is None for m in at_branch.months)  # no value per item and godown
    # The breakdown is the By-godown view's rows for the item.
    assert sum((r.quantity for r in whole.by_godown if r.section in IN_TOTAL), D(0)) == (
        whole.item.closing
    )


def test_an_items_page_at_a_job_workers_godown(db: Session, completed: list[int]) -> None:
    whole = _page(db, completed, "Steel Sheet")
    at_worker = [r for r in whole.by_godown if r.section == "at_job_workers"]
    if not at_worker:
        pytest.skip("no job work on Steel Sheet in this recording")
    page = _page(db, completed, "Steel Sheet", at_worker[0].godown)
    assert {m.godown for m in page.movements} <= {at_worker[0].godown}
    assert page.months[-1].closing == sum((r.quantity for r in at_worker), D(0))
