"""GST details (data completion, part 5).

- `vouchers`: `gst_registration` (the company's tax unit the voucher is under),
  `place_of_supply`, the e-invoice (`irn`, `irn_ack_number`, `irn_date`) and the e-way bill
  (`eway_bill_number`, `eway_bill_date`).
- `parties.gst_registration_type`; `items.gst_taxability`, `gst_classification` (and the
  existing `hsn_code`, `gst_rate` are filled from now on).
- `ledgerbridge_accounting.line_gst_rates`: a ledger or inventory line's GST rate per duty
  head, when the line carries its own.
- `ledgerbridge_accounting.tax_units`: the company's tax registrations (Tally: Tax Unit), a
  master like the others.

NULL and empty before the next fetch.

Revision ID: 0034
Revises: 0033
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"
ID = sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql").with_variant(
    sa.Integer(), "sqlite"
)
TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
VOUCHER_COLUMNS = (
    ("gst_registration", sa.String(length=255)),
    ("place_of_supply", sa.String(length=64)),
    ("irn", sa.String(length=128)),
    ("irn_ack_number", sa.String(length=64)),
    ("irn_date", sa.Date()),
    ("eway_bill_number", sa.String(length=64)),
    ("eway_bill_date", sa.Date()),
)
ITEM_COLUMNS = (
    ("gst_taxability", sa.String(length=32)),
    ("gst_classification", sa.String(length=255)),
)


def upgrade() -> None:
    for name, type_ in VOUCHER_COLUMNS:
        op.add_column("vouchers", sa.Column(name, type_, nullable=True), schema=ACCOUNTING)
    for name, type_ in ITEM_COLUMNS:
        op.add_column("items", sa.Column(name, type_, nullable=True), schema=ACCOUNTING)
    op.add_column(
        "parties",
        sa.Column("gst_registration_type", sa.String(length=32), nullable=True),
        schema=ACCOUNTING,
    )
    op.create_table(
        "line_gst_rates",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("voucher_id", ID, nullable=False),
        sa.Column("entity_id", ID, nullable=False),
        sa.Column("voucher_line_id", ID, nullable=True),
        sa.Column("inventory_line_id", ID, nullable=True),
        sa.Column("duty_head", sa.String(length=32), nullable=False),
        sa.Column("rate", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(["voucher_id"], [f"{ACCOUNTING}.vouchers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], [f"{ACCOUNTING}.entities.id"]),
        sa.ForeignKeyConstraint(
            ["voucher_line_id"], [f"{ACCOUNTING}.voucher_lines.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["inventory_line_id"], [f"{ACCOUNTING}.inventory_lines.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=ACCOUNTING,
    )
    op.create_index(
        op.f("ix_ledgerbridge_accounting_line_gst_rates_voucher_id"),
        "line_gst_rates",
        ["voucher_id"],
        unique=False,
        schema=ACCOUNTING,
    )
    op.create_table(
        "tax_units",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("entity_id", ID, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("gstin", sa.String(length=32), nullable=True),
        sa.Column("state", sa.String(length=64), nullable=True),
        sa.Column("registration_type", sa.String(length=32), nullable=True),
        sa.Column("registered_from", sa.Date(), nullable=True),
        sa.Column("used_for", sa.String(length=32), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("source_key", sa.String(length=191), nullable=False),
        sa.Column("source_alter_id", sa.BigInteger(), nullable=True),
        sa.Column("origin", sa.Enum("live", "backup", "file", "manual", name="origin"), nullable=False),
        sa.Column("raw_record_id", ID, nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column("connection_id", ID, nullable=False),
        sa.Column("import_batch_id", ID, nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(["connection_id"], ["ledgerbridge_system.connections.id"]),
        sa.ForeignKeyConstraint(["entity_id"], [f"{ACCOUNTING}.entities.id"]),
        sa.ForeignKeyConstraint(["import_batch_id"], ["ledgerbridge_system.import_batches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "source_key", name="uq_tax_units_source"),
        schema=ACCOUNTING,
    )
    op.create_index("ix_tax_units_raw_record", "tax_units", ["raw_record_id"], schema=ACCOUNTING)


def downgrade() -> None:
    op.drop_index("ix_tax_units_raw_record", table_name="tax_units", schema=ACCOUNTING)
    op.drop_table("tax_units", schema=ACCOUNTING)
    # Dropping the table drops its index (MySQL won't drop it alone: the foreign key needs it).
    op.drop_table("line_gst_rates", schema=ACCOUNTING)
    op.drop_column("parties", "gst_registration_type", schema=ACCOUNTING)
    for name, _ in reversed(ITEM_COLUMNS):
        op.drop_column("items", name, schema=ACCOUNTING)
    for name, _ in reversed(VOUCHER_COLUMNS):
        op.drop_column("vouchers", name, schema=ACCOUNTING)
