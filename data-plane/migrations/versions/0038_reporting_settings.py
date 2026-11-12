"""Reporting settings read with the statements, for the Trial Balance page (ADR-055).

- `account_groups.nets_for_reporting`: whether the source shows a group's balances netted as
  one figure in its reports (Tally ISADDABLE, "Nett Debit/Credit Balances for Reporting").
- `ledgers.carries_profit`: whether the ledger carries the profit of earlier years (directly
  under the source's Primary, e.g. Tally's Profit & Loss A/c).

Both were read from the source at every statements refresh and used there only; storing them
lets the Trial Balance be laid out on request. NULL until the next statements refresh.

Revision ID: 0038
Revises: 0037
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"


def upgrade() -> None:
    op.add_column(
        "account_groups",
        sa.Column("nets_for_reporting", sa.Boolean(), nullable=True),
        schema=ACCOUNTING,
    )
    op.add_column(
        "ledgers", sa.Column("carries_profit", sa.Boolean(), nullable=True), schema=ACCOUNTING
    )


def downgrade() -> None:
    op.drop_column("ledgers", "carries_profit", schema=ACCOUNTING)
    op.drop_column("account_groups", "nets_for_reporting", schema=ACCOUNTING)
