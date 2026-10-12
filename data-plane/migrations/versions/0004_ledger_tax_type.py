"""M3: ledgers.tax_type, so voucher lines posted to tax ledgers become tax_lines.

Tally names the duty head (Central/State/Integrated Tax, Cess) on the ledger master, not on
each voucher line; storing it on the ledger lets incremental voucher syncs build tax_lines
without re-reading masters (schema.md 4.2 and 7).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ledgers",
        sa.Column(
            "tax_type",
            sa.Enum("cgst", "sgst", "igst", "cess", "tds", "tcs", "vat", "other", name="tax_type"),
            nullable=True,
        ),
        schema="ledgerbridge_accounting",
    )


def downgrade() -> None:
    op.drop_column("ledgers", "tax_type", schema="ledgerbridge_accounting")
