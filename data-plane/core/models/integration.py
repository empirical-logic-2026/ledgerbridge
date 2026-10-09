"""`app` schema integration tables (schema.md Section 5.1)."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, Id, Timestamp, TimestampMixin, VarBinary

CONNECTION_STATUSES = ("active", "paused", "error")
RUN_TYPES = ("incremental", "full", "import")
RUN_STATUSES = ("running", "succeeded", "failed")


class Source(TimestampMixin, Base):
    """A registered connector type, e.g. `tally`."""

    __tablename__ = "sources"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    connector_version: Mapped[str] = mapped_column(String(32))


class Connection(TimestampMixin, Base):
    """One configured connection to a source system."""

    __tablename__ = "connections"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Id, ForeignKey("app.sources.id"))
    name: Mapped[str] = mapped_column(String(255), unique=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Encrypted at application level (CON-009); NULL for sources without credentials.
    credentials_enc: Mapped[bytes | None] = mapped_column(VarBinary, nullable=True)
    # References app.agents once that table exists (SYN-004).
    agent_id: Mapped[int | None] = mapped_column(Id, nullable=True)
    sync_interval_sec: Mapped[int] = mapped_column(Integer, default=300)
    status: Mapped[str] = mapped_column(
        Enum(*CONNECTION_STATUSES, name="connection_status"), default="active"
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class SyncRun(TimestampMixin, Base):
    """One extraction or sync run (SYN-005)."""

    __tablename__ = "sync_runs"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    connection_id: Mapped[int] = mapped_column(Id, ForeignKey("app.connections.id"))
    run_type: Mapped[str] = mapped_column(Enum(*RUN_TYPES, name="sync_run_type"))
    status: Mapped[str] = mapped_column(Enum(*RUN_STATUSES, name="sync_run_status"))
    started_at: Mapped[datetime] = mapped_column(Timestamp)
    finished_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    records_received: Mapped[int] = mapped_column(Integer, default=0)
    records_failed: Mapped[int] = mapped_column(Integer, default=0)
    # Exception type and message only; never payloads or accounting values.
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
