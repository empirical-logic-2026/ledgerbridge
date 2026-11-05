"""Store Tally's source alteration wall-clock timestamp on vouchers.

Tally's UPDATEDDATETIME fixture contains no timezone offset. Preserve its wall-clock
components without converting to UTC or assigning a timezone.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"
SOURCE_DATETIME = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    op.add_column(
        "vouchers",
        sa.Column("source_altered_at", SOURCE_DATETIME, nullable=True),
        schema=ACCOUNTING,
    )


def downgrade() -> None:
    op.drop_column("vouchers", "source_altered_at", schema=ACCOUNTING)
