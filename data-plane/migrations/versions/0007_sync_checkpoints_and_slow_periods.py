"""Resumable large syncs: sync_checkpoints and sync_slow_periods (ADR-022).

A full sync is fetched chunk by chunk (masters per type, vouchers per month or smaller).
Each stored chunk is checkpointed, so an interrupted run continues where it stopped, and
months that had to be split are remembered for later runs (schema.md 5.1).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYSTEM = "ledgerbridge_system"
ID = mysql.BIGINT(unsigned=True)
TIMESTAMP = mysql.DATETIME(fsp=6)


def upgrade() -> None:
    op.create_table(
        "sync_checkpoints",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("connection_id", ID, nullable=False),
        sa.Column("source_entity_key", sa.String(length=191), nullable=False),
        sa.Column("object_type", sa.String(length=64), nullable=False),
        sa.Column("chunk_key", sa.String(length=128), nullable=False),
        sa.Column("records", sa.Integer(), nullable=False),
        sa.Column("sync_run_id", ID, nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(["connection_id"], [f"{SYSTEM}.connections.id"]),
        sa.ForeignKeyConstraint(["sync_run_id"], [f"{SYSTEM}.sync_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "source_entity_key", "chunk_key"),
        schema=SYSTEM,
    )
    op.create_table(
        "sync_slow_periods",
        sa.Column("connection_id", ID, nullable=False),
        sa.Column("source_entity_key", sa.String(length=191), nullable=False),
        sa.Column("object_type", sa.String(length=64), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("piece_days", sa.Integer(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(["connection_id"], [f"{SYSTEM}.connections.id"]),
        sa.PrimaryKeyConstraint("connection_id", "source_entity_key", "object_type", "month"),
        schema=SYSTEM,
    )


def downgrade() -> None:
    op.drop_table("sync_slow_periods", schema=SYSTEM)
    op.drop_table("sync_checkpoints", schema=SYSTEM)
