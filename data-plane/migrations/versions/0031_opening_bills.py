"""Opening bills (data completion, part 2).

`ledgerbridge_accounting.opening_bills`: the bills of a ledger's opening balance (Tally's
bill-wise opening: name, bill date, credit period as a due date, amount), replaced as a whole
with each read of the ledger's opening bills; used by receivables and payables ageing. The
voucher bills' `bill_date` and `due_date` columns exist already (migration 0002) and are now
filled (BILLDATE, BILLCREDITPERIOD).

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"
ID = sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql").with_variant(
    sa.Integer(), "sqlite"
)
TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    op.create_table(
        "opening_bills",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("entity_id", ID, nullable=False),
        sa.Column("ledger_id", ID, nullable=False),
        sa.Column("party_id", ID, nullable=True),
        sa.Column("bill_name", sa.String(length=255), nullable=False),
        sa.Column("bill_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], [f"{ACCOUNTING}.entities.id"]),
        sa.ForeignKeyConstraint(["ledger_id"], [f"{ACCOUNTING}.ledgers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["party_id"], [f"{ACCOUNTING}.parties.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema=ACCOUNTING,
    )
    op.create_index(
        op.f("ix_ledgerbridge_accounting_opening_bills_ledger_id"),
        "opening_bills",
        ["ledger_id"],
        unique=False,
        schema=ACCOUNTING,
    )


def downgrade() -> None:
    # Dropping the table drops its index (MySQL won't drop it alone: the foreign key needs it).
    op.drop_table("opening_bills", schema=ACCOUNTING)
