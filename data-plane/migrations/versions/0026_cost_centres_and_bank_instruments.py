"""Cost categories, allocations by category, and bank instruments.

- `cost_categories` (a source master, per entity): the sets of cost centres a line's amount
  is allocated over; `cost_centres.cost_category_id` and
  `line_cost_allocations.cost_category_id` link to it (NULL before this revision's transform).
- `voucher_lines.instrument_number` (cheque or transfer number) and
  `voucher_lines.transaction_reference` (the bank's unique transaction reference, UTR).
- `ledgerbridge_reporting.v_cost_allocations`: one row per allocation of an effective line of
  a voucher not deleted (entity, date, voucher, ledger, category, cost centre, amount).

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"
ID = sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql").with_variant(
    sa.Integer(), "sqlite"
)
TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")

CREATE_COST_ALLOCATIONS = """CREATE VIEW ledgerbridge_reporting.v_cost_allocations AS
    SELECT vl.entity_id, vl.voucher_date, v.id AS voucher_id, v.voucher_number,
           vt.name AS voucher_type, vl.id AS voucher_line_id, vl.ledger_id, l.name AS ledger,
           a.cost_category_id, cat.name AS cost_category, a.cost_centre_id,
           cc.name AS cost_centre, a.amount
    FROM ledgerbridge_accounting.line_cost_allocations AS a
    JOIN ledgerbridge_accounting.voucher_lines AS vl ON vl.id = a.voucher_line_id
    JOIN ledgerbridge_accounting.vouchers AS v ON v.id = vl.voucher_id
    JOIN ledgerbridge_accounting.voucher_types AS vt ON vt.id = v.voucher_type_id
    JOIN ledgerbridge_accounting.ledgers AS l ON l.id = vl.ledger_id
    JOIN ledgerbridge_accounting.cost_centres AS cc ON cc.id = a.cost_centre_id
    LEFT JOIN ledgerbridge_accounting.cost_categories AS cat ON cat.id = a.cost_category_id
    WHERE vl.is_effective = 1 AND v.is_deleted = 0"""


def upgrade() -> None:
    op.create_table(
        "cost_categories",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("entity_id", ID, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
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
        sa.UniqueConstraint("connection_id", "source_key", name="uq_cost_categories_source"),
        schema=ACCOUNTING,
    )
    op.create_index(
        "ix_cost_categories_raw_record", "cost_categories", ["raw_record_id"], schema=ACCOUNTING
    )
    for table in ("cost_centres", "line_cost_allocations"):
        op.add_column(table, sa.Column("cost_category_id", ID, nullable=True), schema=ACCOUNTING)
        op.create_foreign_key(
            f"fk_{table}_cost_category", table, "cost_categories", ["cost_category_id"], ["id"],
            source_schema=ACCOUNTING, referent_schema=ACCOUNTING,
        )  # fmt: skip
    for column in ("instrument_number", "transaction_reference"):
        op.add_column(
            "voucher_lines", sa.Column(column, sa.String(length=255), nullable=True), schema=ACCOUNTING
        )
    op.execute(CREATE_COST_ALLOCATIONS)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS ledgerbridge_reporting.v_cost_allocations")
    for column in ("transaction_reference", "instrument_number"):
        op.drop_column("voucher_lines", column, schema=ACCOUNTING)
    for table in ("line_cost_allocations", "cost_centres"):
        op.drop_constraint(
            f"fk_{table}_cost_category", table, schema=ACCOUNTING, type_="foreignkey"
        )
        op.drop_column(table, "cost_category_id", schema=ACCOUNTING)
    op.drop_index("ix_cost_categories_raw_record", table_name="cost_categories", schema=ACCOUNTING)
    op.drop_table("cost_categories", schema=ACCOUNTING)
