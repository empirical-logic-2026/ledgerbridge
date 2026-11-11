"""Short-term borrowings: ledgers under Loans (Liability) marked as short-term (F-RAT-008).

- `ledgerbridge_accounting.short_term_borrowings`: one row per marked ledger. A setting a
  person makes (`./dev.ps1 loans mark`), not source data; the ratios count the ledger's
  credit balance as a current liability. Empty until a ledger is marked.

Revision ID: 0037
Revises: 0036
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"
ID = (
    sa.BigInteger()
    .with_variant(mysql.BIGINT(unsigned=True), "mysql")
    .with_variant(sa.Integer(), "sqlite")
)
TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    op.create_table(
        "short_term_borrowings",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("entity_id", ID, nullable=False),
        sa.Column("ledger_id", ID, nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], [f"{ACCOUNTING}.entities.id"]),
        sa.ForeignKeyConstraint(["ledger_id"], [f"{ACCOUNTING}.ledgers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ledger_id", name="uq_short_term_borrowings_ledger"),
        schema=ACCOUNTING,
    )


def downgrade() -> None:
    op.drop_table("short_term_borrowings", schema=ACCOUNTING)
