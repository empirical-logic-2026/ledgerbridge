"""Run liveness and background job output: sync_runs heartbeat/pid/host, status
'interrupted', and sync_logs (ADR-024).

Long syncs run in the background; their output goes to sync_logs so `sync watch` can follow
them from any terminal. A running run's process updates its heartbeat; a run whose heartbeat
stops, or that is stopped with Ctrl+C, is marked 'interrupted' (schema.md 5.1).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYSTEM = "ledgerbridge_system"
ID = mysql.BIGINT(unsigned=True)
TIMESTAMP = mysql.DATETIME(fsp=6)
OLD = ("running", "succeeded", "failed")
NEW = (*OLD, "interrupted")


def _status(old: tuple[str, ...], new: tuple[str, ...]) -> None:
    op.alter_column(
        "sync_runs",
        "status",
        existing_type=sa.Enum(*old, name="sync_run_status"),
        type_=sa.Enum(*new, name="sync_run_status"),
        existing_nullable=False,
        schema=SYSTEM,
    )


def upgrade() -> None:
    _status(OLD, NEW)
    op.add_column("sync_runs", sa.Column("heartbeat_at", TIMESTAMP, nullable=True), schema=SYSTEM)
    op.add_column("sync_runs", sa.Column("pid", sa.Integer(), nullable=True), schema=SYSTEM)
    op.add_column("sync_runs", sa.Column("host", sa.String(length=64), nullable=True), schema=SYSTEM)
    op.create_table(
        "sync_logs",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("connection_id", ID, nullable=False),
        sa.Column("job_id", sa.CHAR(length=36), nullable=False),
        sa.Column("logged_at", TIMESTAMP, nullable=False),
        sa.Column("line", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["connection_id"], [f"{SYSTEM}.connections.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema=SYSTEM,
    )
    op.create_index("ix_sync_logs_job", "sync_logs", ["job_id", "id"], schema=SYSTEM)


def downgrade() -> None:
    op.drop_table("sync_logs", schema=SYSTEM)
    op.drop_column("sync_runs", "host", schema=SYSTEM)
    op.drop_column("sync_runs", "pid", schema=SYSTEM)
    op.drop_column("sync_runs", "heartbeat_at", schema=SYSTEM)
    # Interrupted runs can't be represented in the old type: count them as failed.
    op.execute(
        f"UPDATE {SYSTEM}.sync_runs SET status = 'failed' WHERE status = 'interrupted'"
    )
    _status(NEW, OLD)
