"""Celery application and the scheduled sync (SYN-001, ADR-017).

The worker runs Celery Beat inside it. Every SYNC_TICK_SEC seconds `sync_tick` looks at each
active connection and queues `sync_connection` for those whose own `sync_interval_sec` has
passed since their last sync, or else `deletion_check_connection` when the deletion check
interval (default hourly) has passed since the last deletion check. A Redis lock per
connection keeps runs from overlapping, on top of the database check in workers/sync.py.
"""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from celery import Celery
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.db import get_engine
from core.errors import short_error
from core.models import Connection
from core.models.base import utcnow

if TYPE_CHECKING:
    from workers.sync import SyncResult

logger = logging.getLogger(__name__)
settings = get_settings()

celery_app = Celery("ledgerbridge", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    beat_schedule={
        "sync-tick": {"task": "workers.sync_tick", "schedule": float(settings.sync_tick_sec)},
    },
)

LOCK_TIMEOUT_SEC = 2 * 60 * 60


@celery_app.task(name="workers.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="workers.sync_tick")
def sync_tick() -> list[int]:
    """Queues a sync, or else a deletion check, for every connection that is due.
    Returns the connection ids queued."""
    from workers.sync import (
        DELETION_CHECK,
        deletion_check_interval,
        is_due,
        last_run,
        running_run,
    )

    queued = []
    with Session(get_engine()) as session:
        now = utcnow()
        for connection in session.scalars(select(Connection).where(Connection.status == "active")):
            if running_run(session, connection.id) is not None:
                continue
            previous = last_run(session, connection.id)
            if is_due(connection, previous.started_at if previous else None, now):
                sync_connection.delay(connection.id)
                queued.append(connection.id)
                continue
            check = last_run(session, connection.id, (DELETION_CHECK,))
            interval = deletion_check_interval(connection)
            if is_due(connection, check.started_at if check else None, now, interval):
                deletion_check_connection.delay(connection.id)
                queued.append(connection.id)
    return queued


@celery_app.task(name="workers.sync_connection")
def sync_connection(connection_id: int) -> dict[str, object]:
    """One incremental sync of one connection (all its configured entities)."""
    from workers.sync import run_sync

    return _locked_run(connection_id, run_sync)


@celery_app.task(name="workers.deletion_check_connection")
def deletion_check_connection(connection_id: int) -> dict[str, object]:
    """One deletion check of one connection (SYN-003)."""
    from workers.sync import run_deletion_check

    return _locked_run(connection_id, run_deletion_check)


def _locked_run(connection_id: int, runner: Callable[..., "SyncResult"]) -> dict[str, object]:
    """Runs one sync or deletion check, then its alerts and validation (ADR-019).

    "Sync in progress" is marked by this Redis lock and the run's `running` row in sync_runs,
    never by a database lock on the connection. Errors are logged as type and short message
    only: a traceback would print SQL statements and their parameters.
    """
    lock = Redis.from_url(settings.redis_url).lock(
        f"ledgerbridge:sync:{connection_id}", timeout=LOCK_TIMEOUT_SEC, blocking=False
    )
    if not lock.acquire():
        return {"status": "skipped", "reason": "locked"}
    try:
        return _run(connection_id, runner)
    except Exception as exc:  # noqa: BLE001 - see the docstring
        error = short_error(exc, redact=True)
        logger.error("Run for connection %s failed: %s", connection_id, error)
        return {"status": "error", "error": error}
    finally:
        lock.release()


def _run(connection_id: int, runner: Callable[..., "SyncResult"]) -> dict[str, object]:
    from workers.extract import connector_for
    from workers.sync import SyncBusyError
    from workers.validate import AfterRun, alert_for_run, entity_validator

    with Session(get_engine()) as session:
        connection = session.get_one(Connection, connection_id)
        connector = connector_for(session, connection)
        after = AfterRun()
        try:
            # Each entity is validated as soon as it is synced (ADR-022).
            hook = entity_validator(session, connection, connector, after)
            result = runner(session, connection, connector, after_entity=hook)
        except SyncBusyError:
            return {"status": "skipped", "reason": "running"}
        # Counts only: never names or amounts in task results or logs.
        logger.info(
            "Sync run %s (%s): %s (%s objects fetched, %s soft-deleted, %s warnings)",
            result.sync_run_id,
            result.run_type,
            result.status,
            sum(result.fetched.values()),
            sum(result.deleted.values()),
            len(result.warnings),
        )
        alert_for_run(session, connection, result)
        return {
            "sync_run_id": result.sync_run_id,
            "status": result.status,
            "validation": after.validation_status,
        }
