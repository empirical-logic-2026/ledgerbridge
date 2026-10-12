"""Unverified ranges of a sync: sync_unverified_ranges (ADR-023).

A date range whose stored records couldn't be proven complete is recorded, and fetched
again on every run until it verifies (schema.md 5.1).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYSTEM = "ledgerbridge_system"
ID = mysql.BIGINT(unsigned=True)
TIMESTAMP = mysql.DATETIME(fsp=6)


def upgrade() -> None:
    op.create_table(
        "sync_unverified_ranges",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("connection_id", ID, nullable=False),
        sa.Column("source_entity_key", sa.String(length=191), nullable=False),
        sa.Column("object_type", sa.String(length=64), nullable=False),
        sa.Column("period_from", sa.Date(), nullable=False),
        sa.Column("period_to", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("sync_run_id", ID, nullable=True),
        sa.Column("resolved_at", TIMESTAMP, nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(["connection_id"], [f"{SYSTEM}.connections.id"]),
        sa.ForeignKeyConstraint(["sync_run_id"], [f"{SYSTEM}.sync_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema=SYSTEM,
    )
    op.create_index(
        "ix_sync_unverified_open",
        "sync_unverified_ranges",
        ["connection_id", "source_entity_key", "resolved_at"],
        schema=SYSTEM,
    )


def downgrade() -> None:
    op.drop_table("sync_unverified_ranges", schema=SYSTEM)  # drops its indexes too
