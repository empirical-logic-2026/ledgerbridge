"""Vouchers: the source's effective date (DAT-012, ADR-033).

Tally keeps an effective date on each voucher (EFFECTIVEDATE), which can differ from its
date. Its balances count vouchers by their date, not the effective date (checked on the
test company, 2026-10-15); `validate analyse` reports vouchers whose two dates fall on
different sides of a checked date. Existing vouchers get it on `transform rebuild` (the
stored records already hold it).

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"


def upgrade() -> None:
    op.add_column(
        "vouchers", sa.Column("effective_date", sa.Date(), nullable=True), schema=ACCOUNTING
    )


def downgrade() -> None:
    op.drop_column("vouchers", "effective_date", schema=ACCOUNTING)
