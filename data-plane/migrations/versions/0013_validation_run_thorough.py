"""Validation runs: whether the source's controls were compared (a thorough run).

A quick validation (`validate -Quick`, or after an incremental sync) skips voucher counts,
stock, bills and year ends, so those checks have no result. The report compares each
check's count with the previous run of the same kind only (workers/report.py).
NULL for runs made before this column existed.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYSTEM = "ledgerbridge_system"


def upgrade() -> None:
    op.add_column(
        "validation_runs", sa.Column("thorough", sa.Boolean(), nullable=True), schema=SYSTEM
    )


def downgrade() -> None:
    op.drop_column("validation_runs", "thorough", schema=SYSTEM)
