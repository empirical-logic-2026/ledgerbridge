"""A sync must not keep the connection row locked (pilot run, 2026-10-12).

MySQL takes a shared lock on the referenced `connections` row for every insert into a table
with a foreign key to it (sync_runs, raw_records, every canonical row), held until the
transaction commits. A sync that keeps one transaction open while it waits for the source
therefore blocks `UPDATE connections` (e.g. `connect`) until MySQL gives up with error 1205.

This test syncs the recorded fixtures and, in the middle of fetching, changes the
connection from a second session that waits at most 3 seconds for a lock.
"""

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from connectors.base import Chunk, Markers, SourceEntity, SourceRecord
from connectors.tally.connector import TallyConnector
from connectors.tally.fixtures import DEFAULT_DIR, FixtureTransport
from core.db import get_engine
from core.models import system as S  # noqa: N812
from tests.test_migrations_integration import _config
from tests.test_sync_integration import CONNECTION, _cleanup
from workers.extract import get_or_create_connection
from workers.sync import run_sync

pytestmark = pytest.mark.integration


class ProbingConnector(TallyConnector):
    """Fixture connector that tries to update the connection while the sync waits for the
    source: before the third voucher month (masters and two months already stored)."""

    probe_results: list[str]
    connection_id: int
    voucher_chunks: int = 0

    def fetch_chunk(
        self, entity: SourceEntity, chunk: Chunk, markers: Markers | None
    ) -> list[SourceRecord]:
        if chunk.object_type == "voucher":
            self.voucher_chunks += 1
            if self.voucher_chunks == 3:
                self.probe_results.append(_try_update(self.connection_id))
        return super().fetch_chunk(entity, chunk, markers)


def _try_update(connection_id: int) -> str:
    with Session(get_engine()) as other:
        other.execute(text("SET SESSION innodb_lock_wait_timeout = 3"))
        try:
            other.execute(
                text(
                    "UPDATE ledgerbridge_system.connections SET status = status, "
                    "updated_at = updated_at WHERE id = :id"
                ),
                {"id": connection_id},
            )
            other.commit()
        except OperationalError as exc:
            other.rollback()
            return f"blocked ({exc.orig.args[0]})"
    return "ok"


def test_connection_row_can_be_updated_while_a_sync_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not (DEFAULT_DIR / "manifest.json").exists():
        pytest.skip("no recorded fixtures")
    command.upgrade(_config(), "head")
    monkeypatch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )
    connector = ProbingConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=FixtureTransport(DEFAULT_DIR)
    )
    with Session(get_engine()) as session:
        _cleanup(session)
        try:
            connection = get_or_create_connection(session, CONNECTION, "tally")
            session.commit()
            connector.probe_results, connector.connection_id = [], connection.id
            result = run_sync(session, connection, connector)
            assert result.status == "succeeded", result.error
            assert connector.probe_results == ["ok"]
            assert session.get(S.Connection, connection.id) is not None
        finally:
            _cleanup(session)
