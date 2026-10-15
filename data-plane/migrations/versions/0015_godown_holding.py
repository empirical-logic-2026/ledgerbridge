"""Godowns: whose stock they hold (ADR-031).

Tally leaves stock at an "our stock with third party" godown (e.g. a job worker's
location) out of every stock balance, the Stock Summary and the closing stock value, and
counts stock at a "third-party stock with us" godown (checked on the test company,
2026-10-15). Stock validation and stock reports leave out lines at `ours_with_third_party`
godowns (schema.md 7.5). Existing godowns are `own` until the next full sync fetches the flags.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"
HOLDINGS = ("own", "ours_with_third_party", "third_party_with_us")


def upgrade() -> None:
    op.add_column(
        "godowns",
        sa.Column(
            "holding",
            sa.Enum(*HOLDINGS, name="godown_holding"),
            nullable=False,
            server_default="own",
        ),
        schema=ACCOUNTING,
    )


def downgrade() -> None:
    op.drop_column("godowns", "holding", schema=ACCOUNTING)
