"""Orders (data completion, part 4).

- `inventory_lines.order_number`, `order_due_date`: the sales or purchase order a line
  belongs to (on the order) or is against (on an invoice, delivery or receipt note), from
  the batch allocation's ORDERNO and ORDERDUEDATE.
- `ledgerbridge_accounting.voucher_orders`: the orders a voucher is made against (Tally's
  INVOICEORDERLIST: order number and date; BASICORDERREF), with the order voucher when one
  with that number is stored. Replaced with the voucher's other child rows.

NULL and empty before the next fetch.

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"
ID = sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql").with_variant(
    sa.Integer(), "sqlite"
)
TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    op.add_column(
        "inventory_lines",
        sa.Column("order_number", sa.String(length=255), nullable=True),
        schema=ACCOUNTING,
    )
    op.add_column(
        "inventory_lines", sa.Column("order_due_date", sa.Date(), nullable=True), schema=ACCOUNTING
    )
    op.create_table(
        "voucher_orders",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("voucher_id", ID, nullable=False),
        sa.Column("entity_id", ID, nullable=False),
        sa.Column("order_number", sa.String(length=255), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=True),
        sa.Column("order_voucher_id", ID, nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(["voucher_id"], [f"{ACCOUNTING}.vouchers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], [f"{ACCOUNTING}.entities.id"]),
        sa.ForeignKeyConstraint(
            ["order_voucher_id"], [f"{ACCOUNTING}.vouchers.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=ACCOUNTING,
    )
    op.create_index(
        op.f("ix_ledgerbridge_accounting_voucher_orders_voucher_id"),
        "voucher_orders",
        ["voucher_id"],
        unique=False,
        schema=ACCOUNTING,
    )


def downgrade() -> None:
    # Dropping the table drops its index (MySQL won't drop it alone: the foreign key needs it).
    op.drop_table("voucher_orders", schema=ACCOUNTING)
    op.drop_column("inventory_lines", "order_due_date", schema=ACCOUNTING)
    op.drop_column("inventory_lines", "order_number", schema=ACCOUNTING)
