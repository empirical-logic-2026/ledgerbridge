"""The data-completion fields end to end on MySQL (sync, transform, API read as report_ro), on the
seeded test company's recordings of 2026-11-06 (tests/fixtures/tally/rules/data-completion,
recorded through the connector's requests with every field parts 1 to 7 fetch). Each part adds
its checks here."""

from collections.abc import Iterator
from datetime import date

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.tally.connector import TallyConnector
from connectors.tally.fixtures import FixtureTransport
from core.db import get_engine
from core.models import accounting as A  # noqa: N812
from tests.conftest import FIXTURES
from tests.test_migrations_integration import _config
from tests.test_sync_integration import CONNECTION, _cleanup
from workers.extract import get_or_create_connection
from workers.sync import run_sync

pytestmark = pytest.mark.integration

RULES = FIXTURES / "tally" / "rules" / "data-completion"


@pytest.fixture(scope="module")
def synced() -> Iterator[int]:
    """The seeded test company synced from its recordings; its entity id."""
    command.upgrade(_config(), "head")
    patch = pytest.MonkeyPatch()
    patch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=FixtureTransport(RULES)
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
        session.commit()
        yield entity_id
        for other in session.scalars(select(A.Entity).where(A.Entity.id != entity_id)):
            other.is_on_hold = False
        session.commit()
    patch.undo()


@pytest.fixture(scope="module")
def client(synced: int) -> TestClient:
    from api.main import create_app

    return TestClient(create_app(), base_url="http://localhost")


def _bank_line(session: Session, entity_id: int, marker: str) -> A.VoucherLine:
    voucher = session.scalar(
        select(A.Voucher.id).where(
            A.Voucher.entity_id == entity_id, A.Voucher.narration.like(f"%[lb-seed:{marker}]%")
        )
    )
    return session.scalars(
        select(A.VoucherLine).where(
            A.VoucherLine.voucher_id == voucher, A.VoucherLine.transaction_type.is_not(None)
        )
    ).one()


def test_part_1_bank_details_and_the_utr_are_stored(synced: int) -> None:
    with Session(get_engine()) as s:
        neft = _bank_line(s, synced, "BANK-3")
        assert (neft.utr, neft.utr_source) == ("HDFCN52026100112345", "narration")
        assert (neft.instrument_number, neft.transaction_type) == ("NEFT", "e-Fund Transfer")
        cheque = _bank_line(s, synced, "BANK-4")
        assert (cheque.instrument_number, cheque.utr) == ("000777", None)
        assert (cheque.instrument_date, cheque.bank_cleared_date) == (
            date(2026, 10, 1),
            date(2026, 10, 2),
        )
        assert cheque.bank_recon_status == "Reconciled"
        imps = _bank_line(s, synced, "BANK-5")
        assert (imps.utr, imps.utr_source) == ("629012345678", "bank_field")


def test_part_1_the_transactions_page_shows_cheque_and_utr_apart(
    client: TestClient, synced: int
) -> None:
    response = client.get("/api/v1/transactions", params={"month": ["2026-10"]})
    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    utrs = {r["utr"]: r["utr_source"] for r in rows if r["utr"]}
    assert utrs == {"HDFCN52026100112345": "narration", "629012345678": "bank_field"}
    cheques = {r["cheque"] for r in rows if r["cheque"]}
    assert {"000777", "NEFT", "IMPS"} <= cheques
    assert all(
        r["tally_bank_entry_id"] is None or r["tally_bank_entry_id"] != r["utr"] for r in rows
    )
