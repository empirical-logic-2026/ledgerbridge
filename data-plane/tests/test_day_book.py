"""The Day Book page (ADR-057) against Tally's own Day Book, recorded day by day on the test
company (tests/fixtures/tally/rules/day_book, 2026-11-13: 24 days, 90 vouchers): every row's
date, Particulars, voucher type and its amount or quantity in the right column, in Tally's
order; and the vouchers of each type equal Tally's voucher lists (F-DAY-001, F-DAY-002)."""

import json
from collections import Counter
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.tally import envelopes, parser
from core.day_book import CANCELLED, DayBookRow, day_book
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.report_periods import Period
from tests.conftest import FIXTURES
from tests.tally_day_book_html import Row, read
from tests.test_statements import _synced

DAY_BOOKS = FIXTURES / "tally" / "rules" / "day_book"
MANIFEST = json.loads((DAY_BOOKS / "manifest.json").read_text(encoding="utf-8"))
DAYS = [date.fromisoformat(d) for d in MANIFEST["days"]]


@pytest.fixture
def books(db: Session, monkeypatch: pytest.MonkeyPatch) -> S.Connection:
    """The test company's books as recorded with its Day Book."""
    return _synced(db, monkeypatch, DAY_BOOKS / "books")


def _indian(value: Decimal) -> str:
    """An amount as Tally writes it: 1,62,830.00."""
    whole, cents = f"{abs(value):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join([*groups, tail]) + "." + cents


def _quantity(value: Decimal, unit: str | None) -> str:
    """A quantity as Tally writes it: "3 Nos", "(-)2 Nos"."""
    number = f"{abs(value).normalize():f}"
    return f"{'(-)' if value < 0 else ''}{number} {unit or ''}".strip()


def _as_tally(row: DayBookRow) -> Row:
    first = second = ""
    if row.debit is not None:
        first = _indian(row.debit)
    if row.credit is not None:
        second = _indian(row.credit)
    if row.inward is not None:
        first = _quantity(row.inward, row.unit)
    if row.outward is not None:
        second = _quantity(row.outward, row.unit)
    return Row(f"{row.on.day}-{row.on:%b-%y}", row.particulars, row.voucher_type, first, second)


def test_every_day_equals_tallys_day_book_row_by_row(db: Session, books: S.Connection) -> None:
    entity_id = db.scalars(select(A.Entity)).one().id
    rows = 0
    for on in DAYS:
        ours = [_as_tally(r) for r in day_book(db, [entity_id], Period(on, on)).rows]
        theirs = read(DAY_BOOKS / f"day_book_{on}.html")
        assert ours == theirs, on
        rows += len(ours)
    assert rows == 90


def test_the_vouchers_of_each_type_equal_tallys_voucher_lists(
    db: Session, books: S.Connection
) -> None:
    """F-DAY-002 over the whole recorded period, and day by day."""
    entity_id = db.scalars(select(A.Entity)).one().id
    theirs: Counter[tuple[date, str]] = Counter()
    for path in sorted(DAY_BOOKS.glob("voucher_counts_*.xml")):
        for element in parser.objects(
            parser.parse_response(path.read_bytes()), envelopes.VOUCHER_COUNTS.object_tag
        ):
            on = parser.tally_date(parser.text_of(element, "DATE"))
            if on is not None:
                theirs[(on, parser.text_of(element, "VOUCHERTYPENAME") or "")] += 1
    period = Period(date.fromisoformat(MANIFEST["start"]), date.fromisoformat(MANIFEST["end"]))
    found = day_book(db, [entity_id], period)
    by_type: Counter[str] = Counter()
    for (on, kind), n in theirs.items():
        if period.start <= on <= period.end:
            by_type[kind] += n
    assert found.counts == dict(by_type)
    ours = Counter((r.on, r.voucher_type) for r in found.rows)
    assert ours == +Counter({k: n for k, n in theirs.items() if period.start <= k[0] <= period.end})


def test_the_tags_mark_vouchers_that_dont_change_the_books(
    db: Session, books: S.Connection
) -> None:
    """Optional vouchers, memoranda and orders are tagged; Particulars stays Tally's; a
    cancelled voucher has "(cancelled)" and no amount."""
    entity_id = db.scalars(select(A.Entity)).one().id
    rows = day_book(db, [entity_id], Period(date(2026, 8, 1), date(2026, 10, 31))).rows
    tagged = {(r.voucher_type, tuple(r.tags)) for r in rows if r.tags}
    assert ("Memorandum", ("memorandum",)) in tagged
    assert ("Sales Order", ("order",)) in tagged and ("Purchase Order", ("order",)) in tagged
    assert sum(1 for r in rows if "optional" in r.tags) == 3
    cancelled = [r for r in rows if r.particulars == CANCELLED]
    assert len(cancelled) == 1
    assert (cancelled[0].debit, cancelled[0].credit) == (None, None)


def test_the_api_filters_by_voucher_type_and_party(db: Session, books: S.Connection) -> None:
    """GET /api/v1/day-book: the rows of the chosen types or parties; the counts and the
    filters' choices cover the whole period."""
    from fastapi.testclient import TestClient

    from api.deps import get_report_session
    from api.main import create_app

    app = create_app()
    app.dependency_overrides[get_report_session] = lambda: db
    api = TestClient(app, base_url="http://localhost")
    period = {"date_from": "2026-09-01", "date_to": "2026-10-02"}
    whole = api.get("/api/v1/day-book", params=period).json()
    assert "Payment" in whole["voucher_types"] and whole["parties"]
    payments = api.get("/api/v1/day-book", params={**period, "voucher_type": "Payment"}).json()
    assert payments["rows"] and {r["voucher_type"] for r in payments["rows"]} == {"Payment"}
    assert payments["counts"] == whole["counts"]
    party = whole["parties"][0]
    theirs = api.get("/api/v1/day-book", params={**period, "party": party}).json()["rows"]
    assert theirs and {r["party"] for r in theirs} == {party}


def test_the_mapping_reads_a_voucher_types_place_from_its_guid() -> None:
    from connectors.tally.mapping import master_order

    assert master_order("fbbe2b88-8715-4cff-bea3-c8b0f45e20a0-00000020") == 32
    assert master_order("fbbe2b88-8715-4cff-bea3-c8b0f45e20a0-0000011d") == 285
    assert master_order("not-a-guid") is None
