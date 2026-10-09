"""`raw` schema: source data exactly as received (schema.md Section 3)."""

from datetime import datetime

from sqlalchemy import CHAR, BigInteger, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, Id, LongText, Timestamp, TimestampMixin

PAYLOAD_FORMATS = ("xml", "json", "csv", "txt")
PROCESS_STATUSES = ("pending", "processed", "failed", "skipped")


class RawRecord(TimestampMixin, Base):
    __tablename__ = "raw_records"
    __table_args__ = (
        Index("ix_raw_records_conn_type_key", "connection_id", "object_type", "source_key"),
        Index("ix_raw_records_status_received", "process_status", "received_at"),
        {"schema": "raw"},
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    connection_id: Mapped[int] = mapped_column(Id, ForeignKey("app.connections.id"))
    sync_run_id: Mapped[int | None] = mapped_column(
        Id, ForeignKey("app.sync_runs.id"), nullable=True
    )
    # References app.import_batches once that table exists.
    import_batch_id: Mapped[int | None] = mapped_column(Id, nullable=True)
    source_entity_key: Mapped[str] = mapped_column(String(191))
    object_type: Mapped[str] = mapped_column(String(64))
    source_key: Mapped[str] = mapped_column(String(191))
    source_alter_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    payload_format: Mapped[str] = mapped_column(Enum(*PAYLOAD_FORMATS, name="payload_format"))
    payload: Mapped[str] = mapped_column(LongText)
    payload_hash: Mapped[str] = mapped_column(CHAR(64))
    received_at: Mapped[datetime] = mapped_column(Timestamp)
    process_status: Mapped[str] = mapped_column(
        Enum(*PROCESS_STATUSES, name="process_status"), default="pending"
    )
    process_error: Mapped[str | None] = mapped_column(Text, nullable=True)
