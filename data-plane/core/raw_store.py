"""Writes source records unchanged to ledgerbridge_source.raw_records (schema.md 3 and 8)."""

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from connectors.base import SourceRecord
from core.models import RawRecord
from core.models.base import utcnow


@dataclass
class StoreResult:
    received: int = 0
    stored: int = 0
    skipped: int = 0
    requeued: int = 0  # unchanged, but marked pending again (reprocess_unchanged)


def payload_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class RawStore:
    """Stores records in short transactions: one insert and commit per batch.

    Records arrive from a source that can take minutes per request. Nothing is written while
    waiting for it, because every insert here locks the referenced `connections` row (a
    foreign key) until the transaction commits, which would block changes to the
    connection for the whole sync (MySQL error 1205 in the first pilot run).
    """

    def __init__(self, session: Session, batch_size: int = 500) -> None:
        self._session = session
        self._batch_size = batch_size

    def _latest(self, connection_id: int, record: SourceRecord) -> tuple[int, str] | None:
        stmt = (
            select(RawRecord.id, RawRecord.payload_hash)
            .where(
                RawRecord.connection_id == connection_id,
                RawRecord.object_type == record.object_type,
                RawRecord.source_key == record.source_key,
            )
            .order_by(RawRecord.id.desc())
            .limit(1)
        )
        row = self._session.execute(stmt).first()
        return (row[0], row[1]) if row else None

    def add(
        self,
        records: Iterable[SourceRecord],
        connection_id: int,
        sync_run_id: int | None = None,
        import_batch_id: int | None = None,
        reprocess_unchanged: bool = False,
    ) -> StoreResult:
        """Store records, skipping any whose payload is unchanged since the last delivery.

        With reprocess_unchanged (full syncs), an unchanged record's stored row is marked
        pending again, so the transform re-applies the current mapping rules to it.
        Each batch is committed as soon as it is full, and the rest at the end.
        """
        result = StoreResult()
        rows: list[dict[str, Any]] = []
        requeue: list[int] = []
        buffered: dict[tuple[str, str], str] = {}  # (object_type, key) -> hash, this batch

        def flush() -> None:
            if rows:
                self._session.execute(insert(RawRecord), rows)
            if requeue:
                self._session.execute(
                    update(RawRecord)
                    .where(RawRecord.id.in_(requeue))
                    .values(process_status="pending", process_error=None)
                )
            self._session.commit()
            rows.clear()
            requeue.clear()
            buffered.clear()

        for record in records:
            result.received += 1
            digest = payload_hash(record.payload)
            key = (record.object_type, record.source_key)
            latest_id: int | None = None
            if key in buffered:  # delivered twice in this batch, not written yet
                latest_hash: str | None = buffered[key]
            else:
                latest = self._latest(connection_id, record)
                latest_id, latest_hash = latest if latest else (None, None)
            if latest_hash == digest:
                result.skipped += 1
                if reprocess_unchanged and latest_id is not None:
                    requeue.append(latest_id)
                    result.requeued += 1
            else:
                now = utcnow()
                rows.append(
                    {
                        "connection_id": connection_id,
                        "sync_run_id": sync_run_id,
                        "import_batch_id": import_batch_id,
                        "source_entity_key": record.source_entity_key,
                        "object_type": record.object_type,
                        "source_key": record.source_key,
                        "source_alter_id": record.source_alter_id,
                        "payload_format": record.payload_format,
                        "payload": record.payload,
                        "payload_hash": digest,
                        "received_at": now,
                        "process_status": "pending",
                        "created_at": now,
                        "updated_at": now,
                    }
                )
                buffered[key] = digest
                result.stored += 1
            if len(rows) + len(requeue) >= self._batch_size:
                flush()
        flush()
        return result
