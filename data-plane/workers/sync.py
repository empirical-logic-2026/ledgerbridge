"""Source-independent sync: connector → raw records → canonical tables (architecture 4.4).

One run covers one connection and one or more entities (companies):

Entity by entity (ADR-022):

1. Masters and transactions changed since each object type's marker are fetched (everything
   on the first run or with full=True) and stored unchanged in ledgerbridge_source, chunk by
   chunk when the connector supports it (workers/fetch.py: commit and checkpoint per chunk,
   split slow chunks, check the source after a timeout, resume an interrupted full sync).
2. The entity's pending raw records are transformed into ledgerbridge_accounting
   (core/transform.py), and `after_entity` runs (e.g. validation), before the next entity.
3. The entity's markers advance only after both succeeded, so a failed entity is simply
   repeated. A failing entity doesn't stop the others, except when the source has stopped
   answering altogether.

Deletions (SYN-003) are found by a separate deletion check run (`run_deletion_check`): it
lists every key that exists in the source and soft-deletes rows whose key has gone. Listing
every key costs far more than an incremental sync, so it has its own, longer schedule
(`deletion_check_interval`, default hourly; schema.md 7.4).

Each run is logged in ledgerbridge_system.sync_runs (SYN-005). A connection never has two
runs at once: a run that is still `running` blocks the next one, unless it is stale.
"""

import logging
import os
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from connectors.base import Connector, Period, SourceEntity, SourceUnresponsiveError
from core.config import get_settings
from core.errors import short_error
from core.models import Connection, SyncRun
from core.models.base import utcnow
from core.models.system import SyncMarker
from core.raw_store import RawStore
from core.transform import Transformer, TransformResult, mark_deleted
from workers.entities import Labels, select_entities
from workers.fetch import AUTO, ChunkFetcher, FetchSettings
from workers.runs import (
    INTERRUPTED_BY_SIGNAL,
    RunHeartbeat,
    heartbeat_for,
    reap_stale_runs,
    this_host,
)

logger = logging.getLogger(__name__)

SYNC_RUN_TYPES = ("incremental", "full")
PROGRESS_EVERY = 5000  # records between progress lines
Progress = Callable[[str], None]


def _quiet(message: str) -> None:
    """Default progress sink: nothing."""


DELETION_CHECK = "deletion_check"
TRANSFORM = "transform"


class SyncBusyError(RuntimeError):
    """Another run of the same connection is still in progress."""


@dataclass
class EntityOutcome:
    """One entity's part of a run (counts only; `name` is for test output)."""

    label: str  # "entity 3 (company 2)": workers.entities.Labels
    name: str
    key: str
    status: str = "not attempted"  # succeeded / failed / not attempted
    fetched: int = 0
    stored: int = 0
    unchanged: int = 0
    transformed: int = 0
    transform_failed: int = 0
    chunks: int = 0
    chunks_skipped: int = 0  # completed by an earlier attempt
    splits: int = 0
    retries: int = 0
    unverified: int = 0
    error: str | None = None


AfterEntity = Callable[["SyncResult", SourceEntity, bool], None]


@dataclass
class SyncResult:
    sync_run_id: int
    status: str
    run_type: str
    entities: list[str] = field(default_factory=list)  # names, for display
    entity_keys: list[str] = field(default_factory=list)  # how later steps find them
    fetched: Counter[str] = field(default_factory=Counter)
    stored: int = 0
    unchanged: int = 0
    transformed: Counter[str] = field(default_factory=Counter)
    failed: int = 0
    deleted: dict[str, int] = field(default_factory=dict)
    unmapped_ledgers: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    # Values kept in extra because they didn't fit their column: kind and column -> count.
    data_warnings: Counter[str] = field(default_factory=Counter)
    failed_by_object_type: Counter[str] = field(default_factory=Counter)
    retried: int = 0  # failed records set back to pending (transform retry)
    error: str | None = None
    entity_results: list[EntityOutcome] = field(default_factory=list)


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
    """The connection's run in progress, if its process is alive. Runs left `running`
    without a live process are marked interrupted first (ADR-024)."""
    reap_stale_runs(session, connection_id)
    return session.scalar(
        select(SyncRun)
        .where(SyncRun.connection_id == connection_id, SyncRun.status == "running")
        .order_by(SyncRun.id.desc())
        .limit(1)
    )


def run_sync(
    session: Session,
    connection: Connection,
    connector: Connector,
    entity_names: Sequence[str] | None = None,
    full: bool = False,
    period: Period | None = None,
    progress: Progress | None = None,
    restart: bool = False,
    after_entity: AfterEntity | None = None,
    sleep: Callable[[float], None] = time.sleep,
    refetch_from: date | None = None,
) -> SyncResult:
    """`progress`, if given, receives short status lines (counts only, no names).
    `restart` ignores the checkpoints of an interrupted full sync. `after_entity` runs after
    each entity that synced successfully (validation)."""
    say = progress or _quiet
    has_markers = session.scalar(
        select(SyncMarker.connection_id).where(SyncMarker.connection_id == connection.id).limit(1)
    )
    run_type = "full" if full or period is not None or has_markers is None else "incremental"
    run, result = _open_run(session, connection, run_type)
    try:
        entities = select_entities(connector, connection, entity_names)
        result.entities = [e.name for e in entities]
        labels = Labels(session, connection)
        outcomes = [EntityOutcome(labels.for_key(e.key), e.name, e.key) for e in entities]
        result.entity_results = outcomes
        say(f"{len(outcomes)} companies in this run: {', '.join(o.label for o in outcomes)}")
        for entity, outcome in zip(entities, outcomes, strict=True):
            try:
                _sync_entity(
                    session, connection, connector, run, result, entity, outcome,
                    full=full, period=period, restart=restart, say=say, sleep=sleep,
                    refetch_from=refetch_from,
                )  # fmt: skip
            except SourceUnresponsiveError as exc:
                session.rollback()
                outcome.status, outcome.error = "failed", short_error(exc, redact=True)
                say(f"{outcome.label}: FAILED ({outcome.error}); the remaining entities wait")
                break  # the others would only time out too
            except Exception as exc:  # noqa: BLE001 - recorded; the next entity still runs
                session.rollback()
                outcome.status, outcome.error = "failed", short_error(exc, redact=True)
                say(f"{outcome.label}: FAILED ({outcome.error})")
                continue
            outcome.status = "succeeded"
            result.entity_keys.append(entity.key)
            if after_entity is not None:
                after_entity(result, entity, True)
        failed = [o for o in outcomes if o.status != "succeeded"]
        if failed:
            first = next((o for o in failed if o.error), failed[0])
            raise EntitiesFailedError(
                f"{len(failed)} of {len(outcomes)} entities failed or weren't reached "
                f"({first.label}: {first.error or first.status})"
            )
        result.status = run.status = "succeeded"
    except (KeyboardInterrupt, SystemExit):
        _interrupt_run(session, run, result)
        raise
    except Exception as exc:
        _fail_run(session, run, result, exc)
    return _close_run(session, run, result)


class EntitiesFailedError(RuntimeError):
    """Some entities of a run failed; the others completed (counts only)."""


def _sync_entity(
    session: Session,
    connection: Connection,
    connector: Connector,
    run: SyncRun,
    result: SyncResult,
    entity: SourceEntity,
    outcome: EntityOutcome,
    *,
    full: bool,
    period: Period | None,
    restart: bool,
    say: Progress,
    sleep: Callable[[float], None],
    refetch_from: date | None = None,
) -> None:
    """Fetch, store, transform and mark one entity."""
    label = outcome.label
    say(f"{label}: fetching ({result.run_type})")
    markers = {} if full or period else load_markers(session, connection.id, entity.key)
    if hasattr(connector, "fetch_plan"):
        fetcher = ChunkFetcher(
            session,
            connection.id,
            connector,
            run.id,
            say,
            label,
            sleep=sleep,
            settings=fetch_settings(connection),
            on_part_month=lambda result: _store_part_month(session, connection, result),
        )
        try:
            fetcher.fetch_entity(
                entity,
                markers,
                period,
                resumable=full and period is None,
                restart=restart,
                reprocess_unchanged=full,
                refetch_from=refetch_from,
            )
        finally:  # also when it fails: what was stored is stored, and counted
            _store_prefixes(session, connection, connector)
            stats = fetcher.stats
            result.fetched.update(stats.fetched)
            result.stored += stats.stored
            result.unchanged += stats.unchanged
            outcome.fetched = sum(stats.fetched.values())
            outcome.stored, outcome.unchanged = stats.stored, stats.unchanged
            outcome.chunks, outcome.chunks_skipped = stats.chunks, stats.chunks_skipped
            outcome.splits, outcome.unverified = stats.splits, len(stats.unverified)
            outcome.retries = stats.retries
        fetched, stored, unchanged = outcome.fetched, outcome.stored, outcome.unchanged
    else:  # connectors without chunks: one stream per kind
        fetcher = None
        fetched = stored = unchanged = 0
        store = RawStore(session)
        for records in (
            connector.fetch_masters(entity, markers),
            connector.fetch_transactions(entity, markers, period),
        ):
            counts: Counter[str] = Counter()

            def counted(records=records, counts=counts):  # noqa: ANN001, ANN202
                for record in records:
                    counts[record.object_type] += 1
                    yield record

            added = store.add(counted(), connection.id, run.id, reprocess_unchanged=full)
            result.fetched.update(counts)
            fetched += sum(counts.values())
            stored += added.stored
            unchanged += added.skipped
        result.stored += stored
        result.unchanged += unchanged
        outcome.fetched, outcome.stored, outcome.unchanged = fetched, stored, unchanged
    say(f"{label}: fetched {fetched:,}, stored {stored:,} new or changed, {unchanged:,} unchanged")

    say(f"{label}: transforming into the accounting tables")
    transformed = transformer(session, connection, connector, say).run([entity.key])
    _add_transformed(result, outcome, transformed)
    relabelled = Labels(session, connection).for_key(entity.key)
    if relabelled != outcome.label:
        say(f"{outcome.label} is now {relabelled}")
        outcome.label = label = relabelled
    say(f"{label}: transformed {transformed.processed:,} records, {transformed.failed} failed")

    entity_id = entity_ids_for(session, connection.id, [entity.key]).get(entity.key)
    if entity_id is not None:
        result.unmapped_ledgers[entity.name] = unmapped_ledgers(session, entity_id)
    if period is None:
        save_markers(
            session, connection.id, entity.key, stored_markers(session, connection.id, entity.key)
        )
    session.commit()
    if fetcher is not None:
        fetcher.clear_checkpoints(entity)


def transformer(
    session: Session, connection: Connection, connector: Connector, say: Progress
) -> Transformer:
    """A transformer whose progress lines use the shared company labels."""
    origin = str(connection.config.get("origin", "live"))
    return Transformer(
        session,
        connection.id,
        connector,
        origin,
        progress=say,
        label=lambda key, entity_id: Labels(session, connection).for_key(key, entity_id),
    )


def _add_transformed(
    result: SyncResult, outcome: EntityOutcome, transformed: TransformResult
) -> None:
    result.transformed.update(transformed.by_object_type)
    result.failed += transformed.failed
    result.failed_by_object_type.update(transformed.failed_by_object_type)
    result.warnings.extend(transformed.warnings)
    result.data_warnings.update(transformed.data_warnings)
    result.retried += transformed.retried
    outcome.transformed, outcome.transform_failed = transformed.processed, transformed.failed


def run_transform(
    session: Session,
    connection: Connection,
    connector: Connector,
    entity_keys: Sequence[str] | None = None,
    progress: Progress | None = None,
    retry_failed: bool = True,
    after_entity: AfterEntity | None = None,
    rebuild: bool = False,
) -> SyncResult:
    """Transforms the stored raw records again, without contacting the source, entity by
    entity, with the current code: those that failed before (retry_failed) and any left
    pending; with `rebuild` every object of the entities (processed too), from its latest
    raw record. Runs as a `transform` run, so it never overlaps a sync. `after_entity`
    (validation) runs after each entity."""
    from core.models.accounting import EntitySource
    from core.models.source import RawRecord

    say = progress or _quiet
    run, result = _open_run(session, connection, TRANSFORM)
    try:
        if rebuild:
            statuses: tuple[str, ...] = ("processed", "failed", "pending", "skipped")
        else:
            statuses = ("failed", "pending") if retry_failed else ("pending",)
        waiting = select(RawRecord.source_entity_key).where(
            RawRecord.connection_id == connection.id, RawRecord.process_status.in_(statuses)
        )
        keys = (
            list(entity_keys) if entity_keys else sorted(set(session.scalars(waiting.distinct())))
        )
        names = dict(
            session.execute(
                select(EntitySource.source_entity_key, EntitySource.source_entity_name).where(
                    EntitySource.connection_id == connection.id
                )
            ).all()
        )
        labels = Labels(session, connection)
        outcomes = [EntityOutcome(labels.for_key(k), names.get(k, ""), k) for k in keys]
        result.entity_results = outcomes
        result.entities = [o.name for o in outcomes]
        if outcomes:
            say(f"{len(outcomes)} companies to transform: {', '.join(o.label for o in outcomes)}")
        else:
            say("Nothing to transform: no failed or pending records.")
        for outcome in outcomes:
            what = "every stored record" if rebuild else "stored records"
            say(f"{outcome.label}: transforming {what} again (the source isn't contacted)")
            transformed = transformer(session, connection, connector, say).run(
                [outcome.key], retry_failed=retry_failed, rebuild=rebuild
            )
            _add_transformed(result, outcome, transformed)
            outcome.status = "succeeded"
            queued = "records rebuilt" if rebuild else "failed records retried"
            say(
                f"{outcome.label}: {transformed.retried:,} {queued}; transformed "
                f"{transformed.processed:,}, {transformed.failed:,} failed"
            )
            result.entity_keys.append(outcome.key)
            if after_entity is not None:
                after_entity(result, SourceEntity(outcome.key, outcome.name), True)
        result.status = run.status = "succeeded"
    except (KeyboardInterrupt, SystemExit):
        _interrupt_run(session, run, result)
        raise
    except Exception as exc:
        _fail_run(session, run, result, exc)
    return _close_run(session, run, result)


def fetch_settings(connection: Connection) -> FetchSettings:
    """A connection's effective fetch settings: its own values, else the defaults (ADR-023).
    The TALLY_TIMEOUT_SEC setting applies to connections without a timeout of their own."""
    config = connection.config
    return FetchSettings(
        timeout_sec=float(config.get("timeout_sec") or get_settings().tally_timeout_sec),
        pause_sec=float(config.get("pause_sec") or 0),
        part_month=str(config.get("part_month_requests") or AUTO),
    )


def _store_prefixes(session: Session, connection: Connection, connector: Connector) -> None:
    """Remembers undeclared XML prefixes the source used (names only; shown in summary)."""
    seen = set(getattr(connector, "xml_prefixes_seen", set()))
    known = set(connection.config.get("xml_prefixes_seen") or [])
    if seen - known:
        session.rollback()  # a failed fetch may have left the transaction unusable
        connection.config = {**connection.config, "xml_prefixes_seen": sorted(seen | known)}
        session.commit()


def _store_part_month(session: Session, connection: Connection, result: str) -> None:
    """Remembers whether the source answers part-month requests (probed once)."""
    connection.config = {**connection.config, "part_month_requests": result}
    session.commit()


def stored_markers(session: Session, connection_id: int, entity_key: str) -> dict[str, int]:
    """The highest change marker stored per object type: after a completed fetch, everything
    up to it is in ledgerbridge_source (also chunks fetched by an earlier, resumed attempt)."""
    from core.models.source import RawRecord

    return {
        object_type: int(value)
        for object_type, value in session.execute(
            select(RawRecord.object_type, func.max(RawRecord.source_alter_id))
            .where(
                RawRecord.connection_id == connection_id,
                RawRecord.source_entity_key == entity_key,
            )
            .group_by(RawRecord.object_type)
        ).all()
        if value is not None
    }


def run_deletion_check(
    session: Session,
    connection: Connection,
    connector: Connector,
    entity_names: Sequence[str] | None = None,
    progress: Progress | None = None,
    entity_keys: Sequence[str] | None = None,
    after_entity: AfterEntity | None = None,
) -> SyncResult:
    """Soft-deletes canonical rows whose object no longer exists in the source (SYN-003).

    Lists every key in the source per object type (for Tally, GUID-only exports) and compares.
    Entities that were never synced are skipped. `fetched` counts the keys listed.
    """
    say = progress or _quiet
    run, result = _open_run(session, connection, DELETION_CHECK)
    try:
        entities = select_entities(connector, connection, entity_names, entity_keys)
        entity_ids = entity_ids_for(session, connection.id, [e.key for e in entities])
        labels = Labels(session, connection)
        for entity in entities:
            entity_id = entity_ids.get(entity.key)
            if entity_id is None:
                continue
            say(f"{labels.for_key(entity.key)}: checking for deletions")
            result.entities.append(entity.name)
            result.entity_keys.append(entity.key)
            existing = connector.list_keys(entity)
            for object_type, keys in existing.items():
                result.fetched[object_type] += len(keys)
            deleted = mark_deleted(session, connection.id, entity_id, existing)
            for key, count in deleted.items():
                result.deleted[key] = result.deleted.get(key, 0) + count
            if after_entity is not None:
                after_entity(result, entity, bool(deleted))
        session.commit()
        result.status = run.status = "succeeded"
    except (KeyboardInterrupt, SystemExit):
        _interrupt_run(session, run, result)
        raise
    except Exception as exc:
        _fail_run(session, run, result, exc)
    return _close_run(session, run, result)


def _open_run(
    session: Session, connection: Connection, run_type: str
) -> tuple[SyncRun, SyncResult]:
    if running_run(session, connection.id) is not None:
        raise SyncBusyError(f"connection '{connection.name}' already has a sync running")
    now = utcnow()
    run = SyncRun(
        connection_id=connection.id,
        run_type=run_type,
        status="running",
        started_at=now,
        heartbeat_at=now,
        pid=os.getpid(),
        host=this_host(),
    )
    session.add(run)
    session.commit()
    _heartbeats[run.id] = heartbeat_for(session.get_bind(), run.id)  # type: ignore[arg-type]
    return run, SyncResult(sync_run_id=run.id, status="running", run_type=run_type)


_heartbeats: dict[int, RunHeartbeat] = {}


def _interrupt_run(session: Session, run: SyncRun, result: SyncResult) -> None:
    """Ctrl+C or termination: the run is interrupted, its checkpoints kept (ADR-024)."""
    session.rollback()
    result.error = run.error_summary = INTERRUPTED_BY_SIGNAL
    result.status = run.status = "interrupted"
    logger.warning("Sync run %s interrupted", run.id)
    _close_run(session, run, result)


def _fail_run(session: Session, run: SyncRun, result: SyncResult, exc: Exception) -> None:
    session.rollback()
    result.error = run.error_summary = short_error(exc)
    result.status = run.status = "failed"
    logger.error("Sync run %s failed: %s", run.id, type(exc).__name__)


def _close_run(session: Session, run: SyncRun, result: SyncResult) -> SyncResult:
    heartbeat = _heartbeats.pop(run.id, None)
    if heartbeat is not None:
        heartbeat.stop()
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


def entity_ids_for(session: Session, connection_id: int, keys: list[str]) -> dict[str, int]:
    from core.models.accounting import EntitySource

    return dict(
        session.execute(
            select(EntitySource.source_entity_key, EntitySource.entity_id).where(
                EntitySource.connection_id == connection_id,
                EntitySource.source_entity_key.in_(keys),
            )
        ).all()
    )


def deletion_check_interval(connection: Connection) -> int:
    """Seconds between deletion checks: connections.config.deletion_check_interval_sec, else
    the DELETION_CHECK_INTERVAL_SEC setting (default 3600)."""
    configured = connection.config.get("deletion_check_interval_sec")
    return int(configured) if configured else get_settings().deletion_check_interval_sec


def is_due(
    connection: Connection,
    last_started: datetime | None,
    now: datetime,
    interval_sec: int | None = None,
) -> bool:
    """Scheduled runs (SYN-001): due when the connection is active and the interval (default:
    the connection's sync interval) has passed since the last run of that kind started."""
    if connection.status != "active":
        return False
    if last_started is None:
        return True
    interval = connection.sync_interval_sec if interval_sec is None else interval_sec
    return now - last_started >= timedelta(seconds=interval)


def last_run(
    session: Session, connection_id: int, run_types: Sequence[str] = SYNC_RUN_TYPES
) -> SyncRun | None:
    """The latest run of the given kinds (default: syncs, not deletion checks)."""
    return session.scalar(
        select(SyncRun)
        .where(SyncRun.connection_id == connection_id, SyncRun.run_type.in_(list(run_types)))
        .order_by(SyncRun.id.desc())
        .limit(1)
    )
