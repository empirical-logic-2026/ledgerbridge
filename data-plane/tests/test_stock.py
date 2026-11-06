"""The Stock page's figures (core/stock.py; F-STK) on the test company's recordings of
2026-10-22: its books (rules/stock_values/books) and its statements and stock values with
accounts integrated with inventory (rules/stock_values/integrated), stored as
`./dev.ps1 statements` stores them. Quantities must equal Tally's own; values are Tally's."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.tally.connector import TallyConnector
from core import statements
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.report_periods import Period
from core.stock import find_item, item_page, stock_summary
from tests.stock_replay import FOLDER, replay
from tests.test_statements import DATES, _synced

AS_OF = DATES[-1]  # 2026-10-02
PERIOD = Period(date(2026, 4, 1), AS_OF)


def _tally() -> TallyConnector:
    return TallyConnector.from_config(
        {"url": "http://tally.test:9000", "educational": "yes"}, transport=replay("integrated")
    )


@pytest.fixture
def stored(db: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[int]:
    """The books synced and the statements (with the stock values) stored at every date."""
    connection: S.Connection = _synced(db, monkeypatch, FOLDER / "books")
    entity_id = db.scalars(select(A.Entity)).one().id
    tally = _tally()
    entity = tally.list_entities()[0]
    for on in DATES:
        statements.refresh(
            db, entity_id, connection.id, "live", tally.source_statements(entity, on)
        )
    db.commit()
    yield entity_id


def test_closing_quantities_equal_tallys_and_add_up(db: Session, stored: int) -> None:
    summary = stock_summary(db, [stored], PERIOD)
    tally = _tally()
    theirs = tally.stock_quantities(tally.list_entities()[0], AS_OF)
    names = dict(db.execute(select(A.Item.source_key, A.Item.name)).all())
    expected = {names[key]: quantity for key, quantity in theirs.items()}
    assert {row.name: row.closing for row in summary.items} == expected
    for row in summary.items:  # one stretch of adjacent months: opening + in - out = closing
        assert row.opening + row.inward - row.outward == row.closing, row.name
    assert any(row.inward for row in summary.items) and any(row.outward for row in summary.items)


def test_values_are_tallys_at_the_last_stored_date(db: Session, stored: int) -> None:
    summary = stock_summary(db, [stored], PERIOD)
    assert summary.value_on == AS_OF
    stored_total = db.scalar(
        select(A.StockValue.closing_value).where(
            A.StockValue.as_of == AS_OF, A.StockValue.scope == "total"
        )
    )
    assert summary.total_value == stored_total
    items = {
        name: value
        for name, value in db.execute(
            select(A.StockValue.scope_name, A.StockValue.closing_value).where(
                A.StockValue.as_of == AS_OF, A.StockValue.scope == "item"
            )
        )
    }
    assert items, "the items' own values are stored with the statements"
    assert {r.name: r.value for r in summary.items if r.value is not None} == items
    for row in summary.items:
        if row.value is not None and row.closing:
            assert row.rate == (row.value / row.closing).quantize(Decimal("0.01"))
    assert [d for d, _ in summary.by_date] == list(DATES)  # every stored date up to the end
    assert summary.by_date[-1][1] == summary.total_value


def test_values_by_group_and_godown_are_the_top_levels_stored(db: Session, stored: int) -> None:
    summary = stock_summary(db, [stored], PERIOD)
    for scope, found, model in (
        ("stock_group", summary.by_group, A.ItemGroup),
        ("godown", summary.by_godown, A.Godown),
    ):
        tops = set(db.scalars(select(model.name).where(model.parent_id.is_(None))))
        stored_values = {
            name: value
            for name, value in db.execute(
                select(A.StockValue.scope_name, A.StockValue.closing_value).where(
                    A.StockValue.as_of == AS_OF, A.StockValue.scope == scope
                )
            )
            if name in tops and value
        }
        assert dict(found) == stored_values, scope


def test_a_period_before_any_stored_date_has_no_values(db: Session, stored: int) -> None:
    summary = stock_summary(db, [stored], Period(date(2026, 3, 1), date(2026, 3, 31)))
    assert summary.value_on is None and summary.total_value is None
    assert all(row.value is None for row in summary.items)


def test_an_items_page_runs_to_its_closing(db: Session, stored: int) -> None:
    summary = stock_summary(db, [stored], PERIOD)
    moved = next(row for row in summary.items if row.inward and row.outward)
    ref = find_item(db, [stored], moved.item_id)
    assert ref is not None and ref.name == moved.name
    page = item_page(db, [stored], ref, PERIOD)
    assert page.item.closing == moved.closing and page.item.value == moved.value
    assert page.movements and page.movements[-1].balance == moved.closing
    assert sum(m.quantity for m in page.movements) == moved.inward - moved.outward
    assert [m.month for m in page.months][0] == date(2026, 4, 1)
    assert page.months[-1].closing == moved.closing
    assert sum(m.inward for m in page.months) == moved.inward
    assert not page.truncated


def test_an_item_outside_the_companies_is_not_found(db: Session, stored: int) -> None:
    item_id = db.scalars(select(A.Item.id)).first()
    assert item_id is not None
    assert find_item(db, [stored + 1], item_id) is None
    assert find_item(db, [stored], 999_999) is None
