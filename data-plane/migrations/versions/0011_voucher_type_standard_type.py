"""Voucher types: the source's standard type they derive from (ADR-027).

`voucher_types.standard_type` holds the source's own predefined type a voucher type derives
from, through its parent types (e.g. Tally's "Sales Order"), from the source's fixed list of
standard names only. Validation breaks unbalanced vouchers down by it.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"


def upgrade() -> None:
    op.add_column(
        "voucher_types",
        sa.Column("standard_type", sa.String(length=64), nullable=True),
        schema=ACCOUNTING,
    )


def downgrade() -> None:
    op.drop_column("voucher_types", "standard_type", schema=ACCOUNTING)
