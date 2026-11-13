"""Voucher types in the source's own order, for the Day Book (ADR-057).

- `voucher_types.sort_position`: where the source lists the type (Tally: its master id).
  Tally's Day Book lists a day's vouchers type by type in this order, a custom type right
  after the type it derives from. NULL until the voucher types are transformed again
  (`./dev.ps1 transform rebuild`; no source needed: the stored records hold it).

Revision ID: 0039
Revises: 0038
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"


def upgrade() -> None:
    op.add_column(
        "voucher_types", sa.Column("sort_position", sa.Integer(), nullable=True), schema=ACCOUNTING
    )


def downgrade() -> None:
    op.drop_column("voucher_types", "sort_position", schema=ACCOUNTING)
