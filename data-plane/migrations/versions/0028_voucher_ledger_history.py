"""Retain observed voucher versions and their ledger-posting comparisons.

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"
SYSTEM = "ledgerbridge_system"
ID = sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql")
TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
SOURCE_DATETIME = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
MONEY = sa.Numeric(20, 4)
FX_RATE = sa.Numeric(20, 8)


def upgrade() -> None:
    op.create_table(
        "voucher_versions",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("entity_id", ID, nullable=False),
        sa.Column("voucher_id", ID, nullable=False),
        sa.Column("connection_id", ID, nullable=False),
        sa.Column("voucher_source_key", sa.String(191), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("voucher_number", sa.String(255), nullable=False),
        sa.Column("capture_key", sa.String(191), nullable=False),
        sa.Column("raw_record_id", ID, nullable=True),
        sa.Column("payload_hash", sa.CHAR(64), nullable=True),
        sa.Column("source_alter_id", sa.BigInteger(), nullable=True),
        sa.Column("source_altered_at", SOURCE_DATETIME, nullable=True),
        sa.Column("observed_at", TIMESTAMP, nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deletion_detected_at", TIMESTAMP, nullable=True),
        sa.Column("previous_version_id", ID, nullable=True),
        sa.ForeignKeyConstraint(
            ["entity_id"], [f"{ACCOUNTING}.entities.id"], name="fk_voucher_versions_entity"
        ),
        sa.ForeignKeyConstraint(
            ["voucher_id"], [f"{ACCOUNTING}.vouchers.id"], name="fk_voucher_versions_voucher"
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], [f"{SYSTEM}.connections.id"], name="fk_voucher_versions_connection"
        ),
        sa.ForeignKeyConstraint(
            ["previous_version_id"],
            [f"{ACCOUNTING}.voucher_versions.id"],
            name="fk_voucher_versions_previous",
        ),
        sa.UniqueConstraint("connection_id", "capture_key", name="uq_voucher_versions_capture"),
        schema=ACCOUNTING,
    )
    op.create_index(
        "ix_voucher_versions_entity_key",
        "voucher_versions",
        ["entity_id", "voucher_source_key", "id"],
        schema=ACCOUNTING,
    )
    op.create_index(
        "ix_voucher_versions_altered_at",
        "voucher_versions",
        ["source_altered_at"],
        schema=ACCOUNTING,
    )

    op.create_table(
        "voucher_version_lines",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("voucher_version_id", ID, nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("ledger_id", ID, nullable=False),
        sa.Column("ledger_source_key", sa.String(191), nullable=False),
        sa.Column("ledger_name", sa.String(255), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("amount_fc", MONEY, nullable=True),
        sa.Column("currency_name", sa.String(64), nullable=True),
        sa.Column("exchange_rate", FX_RATE, nullable=True),
        sa.Column("is_party_line", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("identity_hash", sa.CHAR(64), nullable=False),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.ForeignKeyConstraint(
            ["voucher_version_id"],
            [f"{ACCOUNTING}.voucher_versions.id"],
            ondelete="CASCADE",
            name="fk_voucher_version_lines_version",
        ),
        sa.ForeignKeyConstraint(
            ["ledger_id"], [f"{ACCOUNTING}.ledgers.id"], name="fk_voucher_version_lines_ledger"
        ),
        schema=ACCOUNTING,
    )
    op.create_index(
        "ix_voucher_version_lines_version",
        "voucher_version_lines",
        ["voucher_version_id", "line_no"],
        schema=ACCOUNTING,
    )
    op.create_index(
        "ix_voucher_version_lines_ledger",
        "voucher_version_lines",
        ["ledger_source_key"],
        schema=ACCOUNTING,
    )

    op.create_table(
        "voucher_ledger_changes",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("previous_version_id", ID, nullable=True),
        sa.Column("version_id", ID, nullable=False),
        sa.Column("previous_line_id", ID, nullable=True),
        sa.Column("new_line_id", ID, nullable=True),
        sa.Column(
            "change_type",
            sa.Enum("added", "modified", "deleted", "ambiguous", name="voucher_ledger_change_type"),
            nullable=False,
        ),
        sa.Column("matching_basis", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(
            ["previous_version_id"],
            [f"{ACCOUNTING}.voucher_versions.id"],
            name="fk_voucher_ledger_changes_previous_version",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            [f"{ACCOUNTING}.voucher_versions.id"],
            ondelete="CASCADE",
            name="fk_voucher_ledger_changes_version",
        ),
        sa.ForeignKeyConstraint(
            ["previous_line_id"],
            [f"{ACCOUNTING}.voucher_version_lines.id"],
            name="fk_voucher_ledger_changes_previous_line",
        ),
        sa.ForeignKeyConstraint(
            ["new_line_id"],
            [f"{ACCOUNTING}.voucher_version_lines.id"],
            name="fk_voucher_ledger_changes_new_line",
        ),
        schema=ACCOUNTING,
    )
    op.create_index(
        "ix_voucher_ledger_changes_version",
        "voucher_ledger_changes",
        ["version_id"],
        schema=ACCOUNTING,
    )
    op.create_index(
        "ix_voucher_ledger_changes_previous_version",
        "voucher_ledger_changes",
        ["previous_version_id"],
        schema=ACCOUNTING,
    )


def downgrade() -> None:
    op.drop_table("voucher_ledger_changes", schema=ACCOUNTING)
    op.drop_table("voucher_version_lines", schema=ACCOUNTING)
    op.drop_table("voucher_versions", schema=ACCOUNTING)
