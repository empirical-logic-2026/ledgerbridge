"""Voucher types: whether their inventory lines move stock (orders and memorandum don't).

Stock validation and stock reports count only inventory lines of vouchers whose type moves
stock (schema.md 4.3, ADR-027).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"


def upgrade() -> None:
    op.add_column(
        "voucher_types",
        sa.Column("moves_stock", sa.Boolean(), server_default=sa.true(), nullable=False),
        schema=ACCOUNTING,
    )


def downgrade() -> None:
    op.drop_column("voucher_types", "moves_stock", schema=ACCOUNTING)
