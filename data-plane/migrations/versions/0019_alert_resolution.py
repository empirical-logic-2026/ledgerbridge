"""Alerts: why each was resolved (SYN-006).

`alerts.resolution` records the reason an alert was resolved: the run that passed or
succeeded, every company of the connection passing (an alert from before alerts were kept
per entity), or the company being no longer on the connection. Existing resolved alerts
keep it empty.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYSTEM = "ledgerbridge_system"


def upgrade() -> None:
    op.add_column(
        "alerts", sa.Column("resolution", sa.String(255), nullable=True), schema=SYSTEM
    )


def downgrade() -> None:
    op.drop_column("alerts", "resolution", schema=SYSTEM)
