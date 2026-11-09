"""Settings and order (data completion, part 6).

- `account_groups.sort_position`, `ledgers.sort_position`: where the source lists them (Tally
  SORTPOSITION); the statements order primary groups by it.
- `ledgers.affects_stock` (Tally AFFECTSSTOCK).
- `entities.is_integrated`, `is_fifo`, `audited_upto` (Tally ISINTEGRATED, ISFIFOAPPLIED,
  AUDITEDUPTO).
- `vouchers.number_series`, `active_to`, `has_cash_flow` (Tally VOUCHERNUMBERSERIES, ACTIVETO,
  HASCASHFLOW).
- `ledgerbridge_accounting.voucher_number_series`: each voucher type's numbering series.

NULL and empty before the next fetch.

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"
ID = sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql").with_variant(
    sa.Integer(), "sqlite"
)
TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
COLUMNS = (
    ("account_groups", "sort_position", sa.Integer()),
    ("ledgers", "sort_position", sa.Integer()),
    ("ledgers", "affects_stock", sa.Boolean()),
    ("entities", "is_integrated", sa.Boolean()),
    ("entities", "is_fifo", sa.Boolean()),
    ("entities", "audited_upto", sa.Date()),
    ("vouchers", "number_series", sa.String(length=255)),
    ("vouchers", "active_to", sa.Date()),
    ("vouchers", "has_cash_flow", sa.Boolean()),
)


def upgrade() -> None:
    for table, name, type_ in COLUMNS:
        op.add_column(table, sa.Column(name, type_, nullable=True), schema=ACCOUNTING)
    op.create_table(
        "voucher_number_series",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("entity_id", ID, nullable=False),
        sa.Column("voucher_type_id", ID, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("numbering_method", sa.String(length=64), nullable=True),
        sa.Column("numbering_sub_method", sa.String(length=64), nullable=True),
        sa.Column("beginning_number", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("prefill_zero", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("prevent_duplicates", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], [f"{ACCOUNTING}.entities.id"]),
        sa.ForeignKeyConstraint(
            ["voucher_type_id"], [f"{ACCOUNTING}.voucher_types.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=ACCOUNTING,
    )
    op.create_index(
        op.f("ix_ledgerbridge_accounting_voucher_number_series_voucher_type_id"),
        "voucher_number_series",
        ["voucher_type_id"],
        unique=False,
        schema=ACCOUNTING,
    )


def downgrade() -> None:
    # Dropping the table drops its index (MySQL won't drop it alone: the foreign key needs it).
    op.drop_table("voucher_number_series", schema=ACCOUNTING)
    for table, name, _ in reversed(COLUMNS):
        op.drop_column(table, name, schema=ACCOUNTING)
