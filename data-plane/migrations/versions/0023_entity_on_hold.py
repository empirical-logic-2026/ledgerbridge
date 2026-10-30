"""Entities: on hold (SYN-007).

`entities.is_on_hold`: sync, validation and statements skip the entity unless it is named
explicitly, the health report lists it separately and leaves it out of the overall verdict,
and dashboards hide it. Set and cleared with `./dev.ps1 on-hold` (audited).

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"


def upgrade() -> None:
    op.add_column(
        "entities",
        sa.Column("is_on_hold", sa.Boolean(), server_default=sa.false(), nullable=False),
        schema=ACCOUNTING,
    )


def downgrade() -> None:
    op.drop_column("entities", "is_on_hold", schema=ACCOUNTING)
