"""Writes source records unchanged to ledgerbridge_source.raw_records (schema.md 3 and 8)."""

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.base import SourceRecord
from core.models import RawRecord
from core.models.base import utcnow


@dataclass
class StoreResult:
    received: int = 0
    stored: int = 0
    skipped: int = 0


def payload_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class RawStore:
    def __init__(self, session: Session, batch_size: int = 500) -> None:
        self._session = session
        self._batch_size = batch_size

    def _latest_hash(self, connection_id: int, record: SourceRecord) -> str | None:
        stmt = (
            select(RawRecord.payload_hash)
            .where(
                RawRecord.connection_id == connection_id,
                RawRecord.object_type == record.object_type,
                RawRecord.source_key == record.source_key,
            )
            .order_by(RawRecord.id.desc())
            .limit(1)
        )
        return self._session.scalar(stmt)

    def add(
        self,
        records: Iterable[SourceRecord],
        connection_id: int,
        sync_run_id: int | None = None,
        import_batch_id: int | None = None,
    ) -> StoreResult:
        """Store records, skipping any whose payload is unchanged since the last delivery."""
        result = StoreResult()
        pending = 0
        for record in records:
            result.received += 1
            digest = payload_hash(record.payload)
            if self._latest_hash(connection_id, record) == digest:
                result.skipped += 1
                continue
            self._session.add(
                RawRecord(
                    connection_id=connection_id,
                    sync_run_id=sync_run_id,
                    import_batch_id=import_batch_id,
                    source_entity_key=record.source_entity_key,
                    object_type=record.object_type,
                    source_key=record.source_key,
                    source_alter_id=record.source_alter_id,
                    payload_format=record.payload_format,
                    payload=record.payload,
                    payload_hash=digest,
                    received_at=utcnow(),
                    process_status="pending",
                )
            )
            result.stored += 1
            pending += 1
            if pending >= self._batch_size:
                self._session.flush()
                pending = 0
        self._session.flush()
        return result
