"""Runs the connector and sign check over fixtures recorded from LedgerBridge Test Co."""

from collections import Counter

import pytest

from connectors.tally.connector import TallyConnector
from connectors.tally.fixtures import DEFAULT_DIR, FixtureTransport
from connectors.tally.signs import check_vouchers

pytestmark = pytest.mark.skipif(
    not (DEFAULT_DIR / "manifest.json").exists(),
    reason="no recorded fixtures yet (python -m connectors.tally.tools capture-fixtures)",
)


@pytest.fixture
def connector() -> TallyConnector:
    return TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=FixtureTransport(DEFAULT_DIR)
    )


def test_recorded_company_is_listed(connector: TallyConnector) -> None:
    (entity,) = connector.list_entities()
    assert entity.name == "LedgerBridge Test Co"
    assert entity.books_from is not None


def test_recorded_objects_have_guids_and_alter_ids(connector: TallyConnector) -> None:
    (entity,) = connector.list_entities()
    records = [*connector.fetch_masters(entity), *connector.fetch_transactions(entity)]
    counts = Counter(r.object_type for r in records)
    assert counts["group"] > 0 and counts["ledger"] > 0 and counts["voucher_type"] > 0
    assert counts["voucher"] > 0
    assert all(r.source_key for r in records)
    assert all(r.source_alter_id is not None for r in records)
    assert len({(r.object_type, r.source_key) for r in records}) == len(records)


def test_recorded_vouchers_confirm_sign_convention(connector: TallyConnector) -> None:
    (entity,) = connector.list_entities()
    assert check_vouchers(connector.voucher_elements(entity)).debits_negative
