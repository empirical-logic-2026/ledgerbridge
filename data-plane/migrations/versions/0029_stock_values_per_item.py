"""Stock page: stock_values.scope 'item'.

The source's own closing value of each stock item at its statement dates, by item name,
beside the total, stock group and godown values (schema.md 4.9; the dashboard's Stock page).
Filled by the next `./dev.ps1 statements` (no re-fetch).

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = ("total", "stock_group", "godown")
NEW = (*OLD, "item")


def _scope(old: tuple[str, ...], new: tuple[str, ...]) -> None:
    op.alter_column(
        "stock_values",
        "scope",
        existing_type=sa.Enum(*old, name="stock_value_scope"),
        type_=sa.Enum(*new, name="stock_value_scope"),
        existing_nullable=False,
        schema="ledgerbridge_accounting",
    )


def upgrade() -> None:
    _scope(OLD, NEW)


def downgrade() -> None:
    # Item values can't be represented in the old type; remove them first.
    op.execute("DELETE FROM ledgerbridge_accounting.stock_values WHERE scope = 'item'")
    _scope(NEW, OLD)
