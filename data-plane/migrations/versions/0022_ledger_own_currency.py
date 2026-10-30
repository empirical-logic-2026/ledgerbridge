"""Ledgers: their own currency (FX-001, ADR-046).

`currency_name` now holds the ledger's own currency as the source names it (Tally
CURRENCYNAME); the currency of its opening's foreign part moves to `opening_currency_name`;
`is_foreign_currency` says whether its own currency is another than the entity's base one;
`currency_code` becomes NULL when the source's currency gives no ISO code (pilot
2026-10-30: every ledger of every company was INR). The values are written by the transform:
after this migration, `transform rebuild`. Until then the opening's currency is copied to its
new column so nothing is lost.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"


def upgrade() -> None:
    op.add_column(
        "ledgers",
        sa.Column("is_foreign_currency", sa.Boolean(), server_default=sa.false(), nullable=False),
        schema=ACCOUNTING,
    )
    op.add_column(
        "ledgers", sa.Column("opening_currency_name", sa.String(64), nullable=True), schema=ACCOUNTING
    )
    op.alter_column(
        "ledgers", "currency_code", existing_type=sa.CHAR(3), nullable=True, schema=ACCOUNTING
    )
    op.execute(
        "UPDATE ledgerbridge_accounting.ledgers SET opening_currency_name = currency_name "
        "WHERE opening_balance_fc IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE ledgerbridge_accounting.ledgers SET currency_code = 'INR' "
        "WHERE currency_code IS NULL"
    )
    op.alter_column(
        "ledgers", "currency_code", existing_type=sa.CHAR(3), nullable=False, schema=ACCOUNTING
    )
    op.drop_column("ledgers", "opening_currency_name", schema=ACCOUNTING)
    op.drop_column("ledgers", "is_foreign_currency", schema=ACCOUNTING)
