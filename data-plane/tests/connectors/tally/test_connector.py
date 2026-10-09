from collections import Counter
from datetime import date

from connectors.base import Period, SourceEntity
from connectors.tally.connector import TallyConnector, month_periods
from connectors.tally.fixtures import FixtureTransport
from tests.conftest import FIXTURES

SYNTHETIC = FIXTURES / "tally_synthetic"


def _connector() -> tuple[TallyConnector, FixtureTransport]:
    transport = FixtureTransport(SYNTHETIC)
    connector = TallyConnector.from_config({"url": "http://tally.test:9000"}, transport=transport)
    return connector, transport


def test_month_periods_cover_range_exactly() -> None:
    periods = list(month_periods(date(2024, 1, 15), date(2024, 3, 10)))
    assert periods == [
        Period(date(2024, 1, 15), date(2024, 1, 31)),
        Period(date(2024, 2, 1), date(2024, 2, 29)),
        Period(date(2024, 3, 1), date(2024, 3, 10)),
    ]


def test_voucher_periods_run_to_today_when_ending_date_is_not_later() -> None:
    connector, _ = _connector()
    today = date.today()
    entity = SourceEntity(key="k", name="n", books_from=today.replace(day=1), books_to=None)
    stale = SourceEntity(key="k", name="n", books_from=date(2024, 4, 1), books_to=date(2024, 4, 1))
    assert connector.voucher_periods(entity)[-1].end == today
    assert connector.voucher_periods(stale)[-1].end == today


def test_list_entities_and_test_connection() -> None:
    connector, _ = _connector()
    assert [e.name for e in connector.list_entities()] == ["Synthetic Test Co"]
    status = connector.test_connection()
    assert status.ok
    assert status.info == {"companies_loaded": "1"}


def test_fetch_masters_and_vouchers() -> None:
    connector, transport = _connector()
    (entity,) = connector.list_entities()
    masters = list(connector.fetch_masters(entity))
    period = Period(date(2024, 4, 1), date(2024, 5, 31))
    vouchers = list(connector.fetch_transactions(entity, period=period))

    assert Counter(r.object_type for r in masters) == {"group": 4, "ledger": 3, "voucher_type": 1}
    assert len(vouchers) == 2
    assert all(r.source_entity_key == entity.key for r in masters + vouchers)
    # April-May: one voucher request per month, each for the named company.
    voucher_requests = [r for r in transport.requests if "<ID>LBVouchers</ID>" in r]
    assert len(voucher_requests) == 2
    assert all(
        "<SVCURRENTCOMPANY>Synthetic Test Co</SVCURRENTCOMPANY>" in r for r in voucher_requests
    )
