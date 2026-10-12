"""Source-independent sync: connector → raw records → canonical tables (architecture 4.4).

One run covers one connection and one or more entities (companies):

1. Masters and transactions changed since each object type's marker are fetched (everything
   on the first run or with full=True) and stored unchanged in ledgerbridge_source.
2. Pending raw records are transformed into ledgerbridge_accounting (core/transform.py).
3. Objects that no longer exist in the source are soft-deleted (SYN-003).
4. Markers advance only after the run succeeded, so a failed run is simply repeated.

Each run is logged in ledgerbridge_system.sync_runs (SYN-005). A connection never has two
runs at once: a run that is still `running` blocks the next one, unless it is stale.
"""

import logging
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.base import Connector, Period, SourceEntity
from core.models import Connection, SyncRun
from core.models.base import utcnow
from core.models.system import SyncMarker
from core.raw_store import RawStore
from core.transform import Transformer, mark_deleted

logger = logging.getLogger(__name__)

STALE_RUN = timedelta(hours=2)


class SyncBusyError(RuntimeError):
    """Another run of the same connection is still in progress."""


@dataclass
class SyncResult:
    sync_run_id: int
    status: str
    run_type: str
    entities: list[str] = field(default_factory=list)
    fetched: Counter[str] = field(default_factory=Counter)
    stored: int = 0
    unchanged: int = 0
    transformed: Counter[str] = field(default_factory=Counter)
    failed: int = 0
    deleted: dict[str, int] = field(default_factory=dict)
    unmapped_ledgers: dict[str, list[str]] = field(default_factory=dict)
    error: str | None = None


def load_markers(session: Session, connection_id: int, entity_key: str) -> dict[str, str]:
    return dict(
        session.execute(
            select(SyncMarker.object_type, SyncMarker.marker_value).where(
                SyncMarker.connection_id == connection_id,
                SyncMarker.source_entity_key == entity_key,
            )
        ).all()
    )


def save_markers(
    session: Session, connection_id: int, entity_key: str, markers: dict[str, int]
) -> None:
    now = utcnow()
    for object_type, value in markers.items():
        row = session.get(SyncMarker, (connection_id, entity_key, object_type))
        if row is None:
            session.add(
                SyncMarker(
                    connection_id=connection_id,
                    source_entity_key=entity_key,
                    object_type=object_type,
                    marker_value=str(value),
                    created_at=now,
                    updated_at=now,
                )
            )
        elif int(row.marker_value) < value:
            row.marker_value = str(value)
            row.updated_at = now


def running_run(session: Session, connection_id: int) -> SyncRun | None:
    return session.scalar(
        select(SyncRun)
        .where(
            SyncRun.connection_id == connection_id,
            SyncRun.status == "running",
            SyncRun.started_at > utcnow() - STALE_RUN,
        )
        .limit(1)
    )


def select_entities(
    connector: Connector, connection: Connection, names: Sequence[str] | None
) -> list[SourceEntity]:
    """The requested entities; else those configured on the connection; else all loaded."""
    available = connector.list_entities()
    wanted = list(names or connection.config.get("entities") or [])
    if not wanted:
        return available
    by_name = {e.name: e for e in available}
    missing = [n for n in wanted if n not in by_name]
    if missing:
        raise LookupError(f"{len(missing)} requested entities are not available in the source")
    return [by_name[n] for n in wanted]


def run_sync(
    session: Session,
    connection: Connection,
    connector: Connector,
    entity_names: Sequence[str] | None = None,
    full: bool = False,
    period: Period | None = None,
) -> SyncResult:
    if running_run(session, connection.id) is not None:
        raise SyncBusyError(f"connection '{connection.name}' already has a sync running")
    has_markers = session.scalar(
        select(SyncMarker.connection_id).where(SyncMarker.connection_id == connection.id).limit(1)
    )
    run_type = "full" if full or period is not None or has_markers is None else "incremental"
    run = SyncRun(
        connection_id=connection.id, run_type=run_type, status="running", started_at=utcnow()
    )
    session.add(run)
    session.commit()
    result = SyncResult(sync_run_id=run.id, status="running", run_type=run_type)
    origin = str(connection.config.get("origin", "live"))
    try:
        entities = select_entities(connector, connection, entity_names)
        result.entities = [e.name for e in entities]
        new_markers: dict[str, dict[str, int]] = {}
        existing_keys: dict[str, dict[str, set[str]]] = {}
        store = RawStore(session)
        for entity in entities:
            markers = {} if full or period else load_markers(session, connection.id, entity.key)
            highest: dict[str, int] = defaultdict(int)

            def counted(records, highest=highest):  # noqa: ANN001, ANN202
                for record in records:
                    result.fetched[record.object_type] += 1
                    if record.source_alter_id is not None:
                        highest[record.object_type] = max(
                            highest[record.object_type], record.source_alter_id
                        )
                    yield record

            for records in (
                connector.fetch_masters(entity, markers),
                connector.fetch_transactions(entity, markers, period),
            ):
                stored = store.add(counted(records), connection.id, run.id)
                result.stored += stored.stored
                result.unchanged += stored.skipped
            session.commit()
            new_markers[entity.key] = dict(highest)
            if period is None:  # a partial period can't tell what was deleted
                existing_keys[entity.key] = connector.list_keys(entity)

        transformed = Transformer(session, connection.id, connector, origin).run(
            [e.key for e in entities]
        )
        result.transformed.update(transformed.by_object_type)
        result.failed = transformed.failed
        entity_ids = _entity_ids(session, connection.id, [e.key for e in entities])
        for entity in entities:
            entity_id = entity_ids.get(entity.key)
            if entity_id is None:
                continue
            if entity.key in existing_keys:
                for key, count in mark_deleted(
                    session, connection.id, entity_id, existing_keys[entity.key]
                ).items():
                    result.deleted[key] = result.deleted.get(key, 0) + count
            result.unmapped_ledgers[entity.name] = unmapped_ledgers(session, entity_id)
            if period is None:
                save_markers(session, connection.id, entity.key, new_markers[entity.key])
        session.commit()
        result.status = run.status = "succeeded"
    except Exception as exc:
        session.rollback()
        result.error = run.error_summary = f"{type(exc).__name__}: {exc}"[:2000]
        result.status = run.status = "failed"
        logger.error("Sync run %s failed: %s", run.id, type(exc).__name__)
    run.records_received = sum(result.fetched.values())
    run.records_failed = result.failed
    run.finished_at = utcnow()
    session.add(run)
    session.commit()
    return result


def unmapped_ledgers(session: Session, entity_id: int) -> list[str]:
    """Ledgers without a standard account (mapping_status 'unmapped'), by name."""
    from core.models.accounting import Ledger

    return list(
        session.scalars(
            select(Ledger.name)
            .where(
                Ledger.entity_id == entity_id,
                Ledger.mapping_status == "unmapped",
                Ledger.is_deleted.is_(False),
            )
            .order_by(Ledger.name)
        )
    )


def _entity_ids(session: Session, connection_id: int, keys: list[str]) -> dict[str, int]:
    from core.models.accounting import EntitySource

    return dict(
        session.execute(
            select(EntitySource.source_entity_key, EntitySource.entity_id).where(
                EntitySource.connection_id == connection_id,
                EntitySource.source_entity_key.in_(keys),
            )
        ).all()
    )


def is_due(connection: Connection, last_started: datetime | None, now: datetime) -> bool:
    """Scheduled sync (SYN-001): due when the connection is active and its interval passed."""
    if connection.status != "active":
        return False
    if last_started is None:
        return True
    return now - last_started >= timedelta(seconds=connection.sync_interval_sec)


def last_run(session: Session, connection_id: int) -> SyncRun | None:
    return session.scalar(
        select(SyncRun)
        .where(SyncRun.connection_id == connection_id)
        .order_by(SyncRun.id.desc())
        .limit(1)
    )
