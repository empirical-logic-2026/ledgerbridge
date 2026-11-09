"""Stock by godown and batch (data completion, part 3).

- `ledgerbridge_accounting.item_opening_batches`: a stock item's opening at each godown and
  batch (Tally's BATCHALLOCATIONS of the item, read for a period from the books' beginning):
  quantity, rate and value; replaced as a whole with each read of the item.
- `inventory_lines.counterpart_godown_id`: the other godown of a move between godowns:
  where an outgoing line's stock goes, where an incoming line's came from. From the batch's
  DESTINATIONGODOWNNAME (a job worker's godown, for Material Out and In) or, for a transfer
  in a stock journal, the voucher's DESTINATIONGODOWN and the godown the item left. NULL
  before the next fetch.

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"
ID = sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql").with_variant(
    sa.Integer(), "sqlite"
)
TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
RATE = sa.Numeric(precision=20, scale=6)


def upgrade() -> None:
    op.create_table(
        "item_opening_batches",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("entity_id", ID, nullable=False),
        sa.Column("item_id", ID, nullable=False),
        sa.Column("godown_id", ID, nullable=True),
        sa.Column("batch_name", sa.String(length=255), nullable=True),
        sa.Column("quantity", RATE, nullable=False),
        sa.Column("rate", RATE, nullable=True),
        sa.Column("value", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], [f"{ACCOUNTING}.entities.id"]),
        sa.ForeignKeyConstraint(["item_id"], [f"{ACCOUNTING}.items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["godown_id"], [f"{ACCOUNTING}.godowns.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema=ACCOUNTING,
    )
    op.create_index(
        op.f("ix_ledgerbridge_accounting_item_opening_batches_item_id"),
        "item_opening_batches",
        ["item_id"],
        unique=False,
        schema=ACCOUNTING,
    )
    op.add_column(
        "inventory_lines", sa.Column("counterpart_godown_id", ID, nullable=True), schema=ACCOUNTING
    )
    op.create_foreign_key(
        "fk_inventory_lines_counterpart_godown", "inventory_lines", "godowns",
        ["counterpart_godown_id"], ["id"], source_schema=ACCOUNTING, referent_schema=ACCOUNTING,
    )  # fmt: skip


def downgrade() -> None:
    op.drop_constraint(
        "fk_inventory_lines_counterpart_godown",
        "inventory_lines",
        schema=ACCOUNTING,
        type_="foreignkey",
    )
    op.drop_column("inventory_lines", "counterpart_godown_id", schema=ACCOUNTING)
    # Dropping the table drops its index (MySQL won't drop it alone: the foreign key needs it).
    op.drop_table("item_opening_batches", schema=ACCOUNTING)
