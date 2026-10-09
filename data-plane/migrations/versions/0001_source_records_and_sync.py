"""M1: ledgerbridge_source.raw_records and the system tables it depends on.

Creates ledgerbridge_system.sources, .connections, .sync_runs and
ledgerbridge_source.raw_records as described in docs/schema.md Sections 3 and 5.1.

Edited in place for the database rename (ADR-016) before any pilot or client database
existed. After the first release, never edit an applied migration: add a new one.

Revision ID: 0001
Revises:
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ID = sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql")
TS = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def _timestamps() -> list[sa.Column]:
    return [sa.Column("created_at", TS, nullable=False), sa.Column("updated_at", TS, nullable=False)]


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("connector_version", sa.String(32), nullable=False),
        *_timestamps(),
        schema="ledgerbridge_system",
    )
    op.create_table(
        "connections",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("source_id", ID, sa.ForeignKey("ledgerbridge_system.sources.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("config", sa.JSON, nullable=False),
        sa.Column(
            "credentials_enc",
            sa.LargeBinary().with_variant(mysql.VARBINARY(4096), "mysql"),
            nullable=True,
        ),
        sa.Column("agent_id", ID, nullable=True),
        sa.Column("sync_interval_sec", sa.Integer, nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "paused", "error", name="connection_status"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(36), nullable=True),
        *_timestamps(),
        schema="ledgerbridge_system",
    )
    op.create_table(
        "sync_runs",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("connection_id", ID, sa.ForeignKey("ledgerbridge_system.connections.id"), nullable=False),
        sa.Column(
            "run_type",
            sa.Enum("incremental", "full", "import", name="sync_run_type"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("running", "succeeded", "failed", name="sync_run_status"),
            nullable=False,
        ),
        sa.Column("started_at", TS, nullable=False),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("records_received", sa.Integer, nullable=False),
        sa.Column("records_failed", sa.Integer, nullable=False),
        sa.Column("error_summary", sa.Text, nullable=True),
        *_timestamps(),
        schema="ledgerbridge_system",
    )
    op.create_table(
        "raw_records",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("connection_id", ID, sa.ForeignKey("ledgerbridge_system.connections.id"), nullable=False),
        sa.Column("sync_run_id", ID, sa.ForeignKey("ledgerbridge_system.sync_runs.id"), nullable=True),
        sa.Column("import_batch_id", ID, nullable=True),
        sa.Column("source_entity_key", sa.String(191), nullable=False),
        sa.Column("object_type", sa.String(64), nullable=False),
        sa.Column("source_key", sa.String(191), nullable=False),
        sa.Column("source_alter_id", sa.BigInteger, nullable=True),
        sa.Column(
            "payload_format",
            sa.Enum("xml", "json", "csv", "txt", name="payload_format"),
            nullable=False,
        ),
        sa.Column("payload", sa.Text().with_variant(mysql.LONGTEXT(), "mysql"), nullable=False),
        sa.Column("payload_hash", sa.CHAR(64), nullable=False),
        sa.Column("received_at", TS, nullable=False),
        sa.Column(
            "process_status",
            sa.Enum("pending", "processed", "failed", "skipped", name="process_status"),
            nullable=False,
        ),
        sa.Column("process_error", sa.Text, nullable=True),
        *_timestamps(),
        schema="ledgerbridge_source",
    )
    op.create_index(
        "ix_raw_records_conn_type_key",
        "raw_records",
        ["connection_id", "object_type", "source_key"],
        schema="ledgerbridge_source",
    )
    op.create_index(
        "ix_raw_records_status_received",
        "raw_records",
        ["process_status", "received_at"],
        schema="ledgerbridge_source",
    )


def downgrade() -> None:
    op.drop_table("raw_records", schema="ledgerbridge_source")
    op.drop_table("sync_runs", schema="ledgerbridge_system")
    op.drop_table("connections", schema="ledgerbridge_system")
    op.drop_table("sources", schema="ledgerbridge_system")
