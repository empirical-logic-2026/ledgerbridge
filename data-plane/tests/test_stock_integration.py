"""`GET /api/v1/stock` and `.../{item_id}` on MySQL, read as report_ro (RPT-014; F-STK): the
recorded test company (tests/fixtures/tally) synced, the source's stock values stored as the
statements store them. Closing quantities must equal Tally's recorded ones (stock_values.xml);
values are the stored ones, at the last stored date within the period. The figures themselves
are proven on the stock replays in tests/test_stock.py."""

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from connectors.tally import envelopes, mapping, parser
from connectors.tally.connector import TallyConnector
from connectors.tally.fixtures import DEFAULT_DIR, FixtureTransport
from core.db import get_engine
from core.models import accounting as A  # noqa: N812
from tests.test_migrations_integration import _config
from tests.test_sync_integration import CONNECTION, _cleanup
from workers.extract import get_or_create_connection
from workers.sync import run_sync

pytestmark = pytest.mark.integration

D = Decimal

MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
VALUED = date(2026, 8, 31)  # the stored date the values are at
LATER = date(2026, 10, 31)  # stored, but after the period


def _tallys_quantities() -> dict[str, D]:
    """Item name -> Tally's recorded closing quantity."""
    body = (DEFAULT_DIR / "stock_values.xml").read_bytes()
    found = {}
    for element in parser.objects(parser.parse_response(body), envelopes.STOCK_VALUES.object_tag):
        found[parser.object_name(element) or ""] = mapping.quantity(
            parser.text_of(element, "CLOSINGBALANCE")
        )[0]
    return found


@pytest.fixture(scope="module")
def synced() -> Iterator[int]:
    """The test company synced, with stock values stored at two dates; its entity id."""
    if not (DEFAULT_DIR / "manifest.json").exists():
        pytest.skip("no recorded fixtures")
    command.upgrade(_config(), "head")
    patch = pytest.MonkeyPatch()
    patch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=FixtureTransport(DEFAULT_DIR)
    )
    with Session(get_engine()) as session:
        _cleanup(session)
        connection = get_or_create_connection(session, CONNECTION, "tally")
        session.commit()
        assert run_sync(session, connection, connector).status == "succeeded"
        entity_id = session.scalar(
            select(A.EntitySource.entity_id).where(A.EntitySource.connection_id == connection.id)
        )
        assert entity_id is not None
        for other in session.scalars(select(A.Entity).where(A.Entity.id != entity_id)):
            other.is_on_hold = True
        items = list(session.scalars(select(A.Item.name).where(A.Item.entity_id == entity_id)))
        now = datetime(2026, 11, 6)
        for on, base in ((VALUED, D(1000)), (LATER, D(5000))):
            rows = [("total", "", base * len(items))]
            rows += [("item", name, base) for name in items]
            for scope, name, value in rows:
                session.add(
                    A.StockValue(
                        entity_id=entity_id, connection_id=connection.id, origin="live",
                        as_of=on, scope=scope, scope_name=name, opening_value=D(0),
                        closing_value=value, read_at=now,
                    )
                )  # fmt: skip
        session.commit()
        yield entity_id
        session.execute(delete(A.StockValue).where(A.StockValue.entity_id == entity_id))
        for other in session.scalars(select(A.Entity).where(A.Entity.id != entity_id)):
            other.is_on_hold = False
        session.commit()
    patch.undo()


@pytest.fixture(scope="module")
def client(synced: int) -> TestClient:
    from api.main import create_app

    return TestClient(create_app(), base_url="http://localhost")


def _get(client: TestClient, path: str, **params: object) -> dict:
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_stock_page_has_tallys_quantities_and_the_stored_values(
    client: TestClient, synced: int
) -> None:
    page = _get(client, "/api/v1/stock", month=MONTHS)
    items = {i["name"]: i for i in page["items"]}
    assert {name: D(i["closing"]) for name, i in items.items()} == _tallys_quantities()
    for i in items.values():
        assert D(i["opening"]) + D(i["inward"]) - D(i["outward"]) == D(i["closing"])
    assert page["value_on"] == VALUED.isoformat()  # the last stored date within the period
    assert {D(i["value"]) for i in items.values()} == {D(1000)}
    assert D(page["total_value"]) == D(1000) * len(items)
    assert [d["date"] for d in page["by_date"]] == [VALUED.isoformat()]
    negative = next(i for i in items.values() if D(i["closing"]) < 0)
    assert D(negative["rate"]) == (D(1000) / D(negative["closing"])).quantize(D("0.01"))


def test_an_items_page_and_its_months(client: TestClient, synced: int) -> None:
    items = _get(client, "/api/v1/stock", month=MONTHS)["items"]
    moved = next(i for i in items if D(i["inward"]) or D(i["outward"]))
    page = _get(client, f"/api/v1/stock/{moved['item_id']}", month=MONTHS)
    assert page["item"]["name"] == moved["name"]
    assert D(page["movements"][-1]["balance"]) == D(moved["closing"])
    assert [m["month"][:7] for m in page["months"]] == MONTHS
    assert D(page["months"][-1]["closing"]) == D(moved["closing"])
    by_month = {m["month"][:7]: m for m in page["months"]}
    assert D(by_month["2026-08"]["value"]) == D(1000)  # the value stored in that month
    assert by_month["2026-09"]["value"] is None  # none stored in September
    assert client.get("/api/v1/stock/999999999", params={"month": MONTHS}).status_code == 404
