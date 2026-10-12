"""Celery application and the scheduled sync (SYN-001, ADR-017).

The worker runs Celery Beat inside it. Every SYNC_TICK_SEC seconds `sync_tick` looks at each
active connection and queues `sync_connection` for those whose own `sync_interval_sec` has
passed since their last run. A Redis lock per connection keeps runs from overlapping, on top
of the database check in workers/sync.py.
"""

import logging

from celery import Celery
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.db import get_engine
from core.models import Connection
from core.models.base import utcnow

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
    """Queues a sync for every connection that is due. Returns the connection ids queued."""
    from workers.sync import is_due, last_run, running_run

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
    return queued


@celery_app.task(name="workers.sync_connection")
def sync_connection(connection_id: int) -> dict[str, object]:
    """One incremental sync of one connection (all its configured entities)."""
    from workers.extract import connector_for
    from workers.sync import SyncBusyError, run_sync

    lock = Redis.from_url(settings.redis_url).lock(
        f"ledgerbridge:sync:{connection_id}", timeout=LOCK_TIMEOUT_SEC, blocking=False
    )
    if not lock.acquire():
        return {"status": "skipped", "reason": "locked"}
    try:
        with Session(get_engine()) as session:
            connection = session.get_one(Connection, connection_id)
            try:
                result = run_sync(session, connection, connector_for(session, connection))
            except SyncBusyError:
                return {"status": "skipped", "reason": "running"}
            # Counts only: never names or amounts in task results or logs.
            logger.info(
                "Sync run %s: %s (%s objects fetched)",
                result.sync_run_id,
                result.status,
                sum(result.fetched.values()),
            )
            return {"sync_run_id": result.sync_run_id, "status": result.status}
    finally:
        lock.release()
