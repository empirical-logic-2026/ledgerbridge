"""M3: sync_runs.run_type 'deletion_check'.

The deletion check (listing every key in the source, SYN-003) runs on its own schedule,
separate from incremental syncs, and is logged as its own run (schema.md 5.1 and 7.4).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = ("incremental", "full", "import")
NEW = (*OLD, "deletion_check")


def _run_type(old: tuple[str, ...], new: tuple[str, ...]) -> None:
    op.alter_column(
        "sync_runs",
        "run_type",
        existing_type=sa.Enum(*old, name="sync_run_type"),
        type_=sa.Enum(*new, name="sync_run_type"),
        existing_nullable=False,
        schema="ledgerbridge_system",
    )


def upgrade() -> None:
    _run_type(OLD, NEW)


def downgrade() -> None:
    # Deletion check runs can't be represented in the old type; remove them first.
    op.execute("DELETE FROM ledgerbridge_system.sync_runs WHERE run_type = 'deletion_check'")
    _run_type(NEW, OLD)
