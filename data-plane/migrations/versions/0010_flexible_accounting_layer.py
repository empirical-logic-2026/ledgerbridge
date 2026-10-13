"""Flexible accounting layer (ADR-025) and transform runs.

- `extra` JSON on every accounting table that receives source data: fields with no column
  (e.g. Tally UDFs) and values that don't fit their column, kept in full.
- `source_fields`: the catalogue of those fields per entity and object type.
- `dimensions.source_object_type` / `source_field`: dimensions promoted from a field.
- Columns that real Tally data exceeded or can exceed are widened (voucher and reference
  numbers, GSTIN, PAN, phone, unit symbols, item codes, HSN, cost centre categories).
- `raw_records.process_warning`: what a processed record had kept aside (kinds only).
- `sync_runs.run_type` gains `transform` (re-transforming stored records, no fetch).

Adding columns and widening VARCHARs that keep their length-byte count are in-place in
MySQL 8, so large tables (vouchers, raw_records) aren't copied.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE = "ledgerbridge_source"
ACCOUNTING = "ledgerbridge_accounting"
SYSTEM = "ledgerbridge_system"
ID = mysql.BIGINT(unsigned=True)
TIMESTAMP = mysql.DATETIME(fsp=6)

EXTRA_TABLES = (
    "entities",
    "account_groups",
    "ledgers",
    "parties",
    "voucher_types",
    "item_groups",
    "units",
    "items",
    "godowns",
    "cost_centres",
    "vouchers",
)
# (table, column, old length, new length, nullable)
WIDENED = (
    ("entities", "gstin", 15, 32, True),
    ("entities", "pan", 10, 32, True),
    ("branches", "gstin", 15, 32, True),
    ("ledgers", "gstin", 15, 32, True),
    ("parties", "gstin", 15, 32, True),
    ("parties", "pan", 10, 32, True),
    ("parties", "phone", 32, 255, True),
    ("units", "symbol", 64, 255, False),
    ("items", "code", 64, 255, True),
    ("items", "hsn_code", 16, 32, True),
    ("tax_lines", "hsn_code", 16, 32, True),
    ("cost_centres", "category", 64, 255, True),
    ("vouchers", "voucher_number", 64, 255, False),
    ("vouchers", "reference_number", 128, 255, True),
)
OLD_RUN_TYPES = ("incremental", "full", "import", "deletion_check")
NEW_RUN_TYPES = (*OLD_RUN_TYPES, "transform")


def _run_types(old: tuple[str, ...], new: tuple[str, ...]) -> None:
    op.alter_column(
        "sync_runs",
        "run_type",
        existing_type=sa.Enum(*old, name="sync_run_type"),
        type_=sa.Enum(*new, name="sync_run_type"),
        existing_nullable=False,
        schema=SYSTEM,
    )


def upgrade() -> None:
    for table in EXTRA_TABLES:
        op.add_column(table, sa.Column("extra", sa.JSON(), nullable=True), schema=ACCOUNTING)
    for table, column, old, new, nullable in WIDENED:
        op.alter_column(
            table,
            column,
            existing_type=sa.String(length=old),
            type_=sa.String(length=new),
            existing_nullable=nullable,
            schema=ACCOUNTING,
        )
    op.add_column(
        "dimensions",
        sa.Column("source_object_type", sa.String(length=64), nullable=True),
        schema=ACCOUNTING,
    )
    op.add_column(
        "dimensions",
        sa.Column("source_field", sa.String(length=255), nullable=True),
        schema=ACCOUNTING,
    )
    op.create_table(
        "source_fields",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("entity_id", ID, nullable=False),
        sa.Column("object_type", sa.String(length=64), nullable=False),
        sa.Column("field_path", sa.String(length=255), nullable=False),
        sa.Column("prefix", sa.String(length=64), nullable=True),
        sa.Column(
            "inferred_type",
            sa.Enum("text", "number", "date", "flag", "mixed", name="source_field_type"),
            nullable=False,
        ),
        sa.Column("record_count", sa.BigInteger(), nullable=False),
        sa.Column("first_seen_at", TIMESTAMP, nullable=False),
        sa.Column("last_seen_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], [f"{ACCOUNTING}.entities.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity_id", "object_type", "field_path", name="uq_source_fields_field"
        ),
        schema=ACCOUNTING,
    )
    op.add_column(
        "raw_records", sa.Column("process_warning", sa.Text(), nullable=True), schema=SOURCE
    )
    _run_types(OLD_RUN_TYPES, NEW_RUN_TYPES)


def downgrade() -> None:
    # Transform runs can't be represented in the old type: count them as full runs.
    op.execute(f"UPDATE {SYSTEM}.sync_runs SET run_type = 'full' WHERE run_type = 'transform'")
    _run_types(NEW_RUN_TYPES, OLD_RUN_TYPES)
    op.drop_column("raw_records", "process_warning", schema=SOURCE)
    op.drop_table("source_fields", schema=ACCOUNTING)
    op.drop_column("dimensions", "source_field", schema=ACCOUNTING)
    op.drop_column("dimensions", "source_object_type", schema=ACCOUNTING)
    # Narrowing fails if longer values were stored since: that is intended (no silent
    # truncation); clear or shorten them first.
    for table, column, old, new, nullable in WIDENED:
        op.alter_column(
            table,
            column,
            existing_type=sa.String(length=new),
            type_=sa.String(length=old),
            existing_nullable=nullable,
            schema=ACCOUNTING,
        )
    for table in EXTRA_TABLES:
        op.drop_column(table, "extra", schema=ACCOUNTING)
