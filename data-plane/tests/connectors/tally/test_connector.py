import logging
from collections import Counter
from datetime import date, timedelta

import httpx
import pytest

from connectors.base import Period, SourceEntity
from connectors.tally.connector import (
    TallyConnector,
    _base_currency,
    _foreign,
    month_end,
    month_periods,
)
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


def test_voucher_periods_run_to_end_of_current_month() -> None:
    connector, _ = _connector()
    today = date.today()
    entity = SourceEntity(key="k", name="n", books_from=today.replace(day=1), books_to=None)
    stale = SourceEntity(key="k", name="n", books_from=date(2024, 4, 1), books_to=date(2024, 4, 1))
    assert connector.voucher_periods(entity)[-1].end == month_end(today)
    assert connector.voucher_periods(stale)[-1].end == month_end(today)
    # Every chunk is a whole month, so every exclusive end date sent to Tally is a 1st.
    assert all((p.end + timedelta(days=1)).day == 1 for p in connector.voucher_periods(stale))


def test_month_end() -> None:
    assert month_end(date(2026, 4, 15)) == date(2026, 4, 30)
    assert month_end(date(2028, 2, 1)) == date(2028, 2, 29)
    assert month_end(date(2026, 12, 31)) == date(2026, 12, 31)


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

    assert Counter(r.object_type for r in masters) == {
        "company": 1,
        "group": 4,
        "ledger": 3,
        "voucher_type": 1,
    }
    assert len(vouchers) == 2
    assert all(r.source_entity_key == entity.key for r in masters + vouchers)
    # April-May: one voucher request per month, each for the named company.
    voucher_requests = [r for r in transport.requests if "<ID>LBVouchers</ID>" in r]
    assert len(voucher_requests) == 2
    assert all(
        "<SVCURRENTCOMPANY>Synthetic Test Co</SVCURRENTCOMPANY>" in r for r in voucher_requests
    )


def test_the_base_currency_is_the_same_on_every_run_and_ambiguity_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ledgers directly under Primary in two currencies: the most used wins, then the
    first by name, whatever order they come in; a warning says it was ambiguous."""
    currencies = {"pl": "?", "x": "$", "y": "€", "z": "€"}
    for carriers in (["pl", "x"], ["x", "pl"]):
        with caplog.at_level(logging.WARNING):
            assert _base_currency(currencies, carriers) == "$"  # "$" sorts before "?"
    assert "Base currency ambiguous" in caplog.text
    caplog.clear()
    assert _base_currency({"pl": "?", "x": "$", "y": "?"}, ["pl"]) == "?"
    assert _foreign({"pl": "?", "x": "$"}, ["pl"]) == {"x"}
    assert caplog.text == ""


def test_an_unreadable_trial_balance_is_logged_with_its_error_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The computed opening difference is still used (None here), and the warning names
    the kind of error, never values."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("broken")

    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=httpx.MockTransport(handler)
    )
    entity = SourceEntity(key="k", name="n", books_from=date(2026, 4, 1))
    with caplog.at_level(logging.WARNING):
        assert connector.opening_difference_shown(entity) is None
    assert "trial balance couldn't be read (RuntimeError)" in caplog.text
