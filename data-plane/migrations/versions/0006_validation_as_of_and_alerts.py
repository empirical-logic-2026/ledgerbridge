"""M4: validation_runs.as_of and alerts.

Validation compares balances as of a date (vouchers dated after it don't count), and
sync or validation failures raise in-app alerts (SYN-006, ADR-019; schema.md 5.2).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYSTEM = "ledgerbridge_system"
ID = mysql.BIGINT(unsigned=True)
TIMESTAMP = mysql.DATETIME(fsp=6)


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column(
            "kind",
            sa.Enum("sync_failed", "deletion_check_failed", "validation_failed", name="alert_kind"),
            nullable=False,
        ),
        sa.Column("severity", sa.Enum("error", "warning", name="alert_severity"), nullable=False),
        sa.Column("connection_id", ID, nullable=False),
        sa.Column("entity_id", ID, nullable=True),
        sa.Column("sync_run_id", ID, nullable=True),
        sa.Column("validation_run_id", ID, nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("resolved_at", TIMESTAMP, nullable=True),
        sa.Column("acknowledged_at", TIMESTAMP, nullable=True),
        sa.Column("acknowledged_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(["connection_id"], [f"{SYSTEM}.connections.id"]),
        sa.ForeignKeyConstraint(["entity_id"], ["ledgerbridge_accounting.entities.id"]),
        sa.ForeignKeyConstraint(["sync_run_id"], [f"{SYSTEM}.sync_runs.id"]),
        sa.ForeignKeyConstraint(["validation_run_id"], [f"{SYSTEM}.validation_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema=SYSTEM,
    )
    op.create_index(
        "ix_alerts_open", "alerts", ["connection_id", "kind", "resolved_at"], schema=SYSTEM
    )
    # Nullable first so existing runs can take their start date, then required.
    op.add_column("validation_runs", sa.Column("as_of", sa.Date(), nullable=True), schema=SYSTEM)
    op.execute(f"UPDATE {SYSTEM}.validation_runs SET as_of = DATE(started_at)")
    op.alter_column(
        "validation_runs", "as_of", existing_type=sa.Date(), nullable=False, schema=SYSTEM
    )


def downgrade() -> None:
    op.drop_column("validation_runs", "as_of", schema=SYSTEM)
    op.drop_table("alerts", schema=SYSTEM)  # drops its indexes too
