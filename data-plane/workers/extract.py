"""Source-independent extraction: connector → ledgerbridge_source.raw_records, logged in
ledgerbridge_system.sync_runs."""

import logging
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors import registry
from connectors.base import Connector, Period, SourceEntity, SourceRecord
from core.models import Connection, Source, SyncRun
from core.models.base import utcnow
from core.raw_store import RawStore

logger = logging.getLogger(__name__)


@dataclass
class ExtractResult:
    sync_run_id: int
    status: str
    received: int = 0
    stored: int = 0
    skipped: int = 0
    by_object_type: Counter[str] = field(default_factory=Counter)
    error: str | None = None


def get_or_create_connection(session: Session, name: str, source_code: str | None) -> Connection:
    """Find a connection by name, or create it with config from settings if a source is given."""
    connection = session.scalar(select(Connection).where(Connection.name == name))
    if connection is not None:
        return connection
    if source_code is None:
        raise ValueError(f"Connection '{name}' does not exist; pass --source to create it")
    source = session.scalar(select(Source).where(Source.code == source_code))
    if source is None:
        display_name, version = registry.SOURCE_INFO[source_code]
        source = Source(code=source_code, name=display_name, connector_version=version)
        session.add(source)
        session.flush()
    connection = Connection(
        source_id=source.id, name=name, config=registry.default_config(source_code)
    )
    session.add(connection)
    session.flush()
    return connection


def connector_for(session: Session, connection: Connection) -> Connector:
    source = session.get_one(Source, connection.source_id)
    return registry.create_connector(source.code, connection.config)


def find_entity(connector: Connector, name: str) -> SourceEntity:
    entities = connector.list_entities()
    for entity in entities:
        if entity.name == name:
            return entity
    raise LookupError(f"Entity '{name}' is not available in the source ({len(entities)} listed)")


def _counted(records: Iterator[SourceRecord], counts: Counter[str]) -> Iterator[SourceRecord]:
    for record in records:
        counts[record.object_type] += 1
        yield record


def run_extract(
    session: Session,
    connection: Connection,
    connector: Connector,
    entity: SourceEntity,
    period: Period | None = None,
) -> ExtractResult:
    """Full extraction of masters and transactions for one entity, in one sync run."""
    run = SyncRun(
        connection_id=connection.id,
        run_type="full",
        status="running",
        started_at=utcnow(),
    )
    session.add(run)
    session.commit()

    result = ExtractResult(sync_run_id=run.id, status="running")
    store = RawStore(session)
    try:
        for records in (
            connector.fetch_masters(entity),
            connector.fetch_transactions(entity, period=period),
        ):
            stored = store.add(_counted(records, result.by_object_type), connection.id, run.id)
            result.received += stored.received
            result.stored += stored.stored
            result.skipped += stored.skipped
        session.commit()
        result.status = run.status = "succeeded"
    except Exception as exc:
        session.rollback()
        # Type and message only; connector errors never include payloads.
        result.error = run.error_summary = f"{type(exc).__name__}: {exc}"[:2000]
        result.status = run.status = "failed"
        logger.error("Sync run %s failed: %s", run.id, type(exc).__name__)
    run.records_received = result.received
    run.finished_at = utcnow()
    session.add(run)
    session.commit()
    return result
