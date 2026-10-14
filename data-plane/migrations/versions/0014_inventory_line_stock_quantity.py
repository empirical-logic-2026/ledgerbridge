"""Inventory lines: the quantity each line moves in stock.

A sales, purchase, debit or credit note line tracked to a delivery or receipt note doesn't
move stock: the note does (Tally, checked on the test company 2026-10-14). `quantity` stays
the invoiced quantity; `stock_quantity` is what moves stock, used by stock validation and
stock reports (schema.md 4.3). Existing lines get their quantity (a sync or rebuild sets the
tracked ones).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"


def upgrade() -> None:
    op.add_column(
        "inventory_lines",
        sa.Column("stock_quantity", sa.Numeric(20, 6), nullable=True),
        schema=ACCOUNTING,
    )
    op.execute(f"UPDATE {ACCOUNTING}.inventory_lines SET stock_quantity = quantity")
    op.alter_column(
        "inventory_lines",
        "stock_quantity",
        existing_type=sa.Numeric(20, 6),
        nullable=False,
        schema=ACCOUNTING,
    )


def downgrade() -> None:
    op.drop_column("inventory_lines", "stock_quantity", schema=ACCOUNTING)
