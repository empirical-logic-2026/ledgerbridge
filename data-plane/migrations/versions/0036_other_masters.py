"""Other masters (data completion, part 7).

- `ledgerbridge_accounting.stock_categories` (a master) and `items.stock_category_id`.
- `items.reorder_level`, `min_order_quantity` (base units).
- `ledgerbridge_accounting.item_prices`: each stock item's price list.
- `ledgerbridge_accounting.source_budgets` (a master) and `source_budget_lines`: the
  budgets kept in the source with their ledger lines; apart from our own budgets
  (schema.md 4.7, M7b).

Empty before the next fetch.

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"
ID = sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql").with_variant(
    sa.Integer(), "sqlite"
)
TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
RATE = sa.Numeric(precision=20, scale=6)


def _source_columns(table: str) -> list[object]:
    """The source-tracking columns and keys every [SRC] master has (schema.md 1.1)."""
    return [
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
        sa.UniqueConstraint("connection_id", "source_key", name=f"uq_{table}_source"),
    ]


def _master(table: str, *columns: object) -> None:
    op.create_table(
        table,
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("entity_id", ID, nullable=False),
        sa.Column("parent_id", ID, nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        *columns,
        *_source_columns(table),
        sa.ForeignKeyConstraint(["parent_id"], [f"{ACCOUNTING}.{table}.id"]),
        schema=ACCOUNTING,
    )
    op.create_index(f"ix_{table}_raw_record", table, ["raw_record_id"], schema=ACCOUNTING)


def _child_index(table: str, column: str) -> None:
    op.create_index(
        op.f(f"ix_ledgerbridge_accounting_{table}_{column}"),
        table,
        [column],
        unique=False,
        schema=ACCOUNTING,
    )


def upgrade() -> None:
    _master("stock_categories")
    _master("source_budgets", sa.Column("use_actuals", sa.Boolean(), nullable=True))
    op.add_column("items", sa.Column("stock_category_id", ID, nullable=True), schema=ACCOUNTING)
    op.create_foreign_key(
        "fk_items_stock_category", "items", "stock_categories", ["stock_category_id"], ["id"],
        source_schema=ACCOUNTING, referent_schema=ACCOUNTING,
    )  # fmt: skip
    op.add_column("items", sa.Column("reorder_level", RATE, nullable=True), schema=ACCOUNTING)
    op.add_column(
        "items", sa.Column("min_order_quantity", RATE, nullable=True), schema=ACCOUNTING
    )
    op.create_table(
        "item_prices",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("entity_id", ID, nullable=False),
        sa.Column("item_id", ID, nullable=False),
        sa.Column("price_level", sa.String(length=255), nullable=False),
        sa.Column("applicable_from", sa.Date(), nullable=True),
        sa.Column("rate", RATE, nullable=True),
        sa.Column("from_quantity", RATE, nullable=True),
        sa.Column("to_quantity", RATE, nullable=True),
        sa.Column("discount_pct", RATE, nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], [f"{ACCOUNTING}.entities.id"]),
        sa.ForeignKeyConstraint(["item_id"], [f"{ACCOUNTING}.items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema=ACCOUNTING,
    )
    _child_index("item_prices", "item_id")
    op.create_table(
        "source_budget_lines",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("budget_id", ID, nullable=False),
        sa.Column("entity_id", ID, nullable=False),
        sa.Column("ledger_id", ID, nullable=True),
        sa.Column("ledger_name", sa.String(length=255), nullable=False),
        sa.Column("period_from", sa.Date(), nullable=True),
        sa.Column("period_to", sa.Date(), nullable=True),
        sa.Column("basis", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["budget_id"], [f"{ACCOUNTING}.source_budgets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["entity_id"], [f"{ACCOUNTING}.entities.id"]),
        sa.ForeignKeyConstraint(["ledger_id"], [f"{ACCOUNTING}.ledgers.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema=ACCOUNTING,
    )
    _child_index("source_budget_lines", "budget_id")


def downgrade() -> None:
    # Dropping a table drops its indexes (MySQL won't drop one a foreign key needs alone).
    op.drop_table("source_budget_lines", schema=ACCOUNTING)
    op.drop_table("item_prices", schema=ACCOUNTING)
    op.drop_column("items", "min_order_quantity", schema=ACCOUNTING)
    op.drop_column("items", "reorder_level", schema=ACCOUNTING)
    op.drop_constraint("fk_items_stock_category", "items", schema=ACCOUNTING, type_="foreignkey")
    op.drop_column("items", "stock_category_id", schema=ACCOUNTING)
    for table in ("source_budgets", "stock_categories"):
        op.drop_index(f"ix_{table}_raw_record", table_name=table, schema=ACCOUNTING)
        op.drop_table(table, schema=ACCOUNTING)
