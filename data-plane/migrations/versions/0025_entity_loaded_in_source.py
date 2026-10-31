"""Entity sources: whether the source had the company loaded when last asked (D1, the
dashboard's company chips).

`entity_sources.source_checked_at`, `source_loaded`, `source_checked_by` (`sync` or
`entity_check`): written by a sync and by `entity-check` from the source's list of loaded
companies, read by the dashboard, which never contacts the source. NULL: never asked.
`v_data_health` also gives the name of the entity's source (e.g. "Tally (XML over HTTP)"),
which `report_ro` can't read from `ledgerbridge_system` itself.

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"
TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")

LATEST_VALIDATION = """(SELECT v.{column} FROM ledgerbridge_system.validation_runs AS v
            WHERE v.entity_id = e.id ORDER BY v.id DESC LIMIT 1)"""
LAST_SYNC = """(SELECT MAX(r.finished_at)
            FROM ledgerbridge_system.sync_runs AS r
            JOIN ledgerbridge_accounting.entity_sources AS es
              ON es.connection_id = r.connection_id
            WHERE es.entity_id = e.id AND r.status = 'succeeded'
              AND r.run_type IN ('full', 'incremental'))"""
SOURCE_NAME = """(SELECT s.name FROM ledgerbridge_accounting.entity_sources AS es
            JOIN ledgerbridge_system.connections AS c ON c.id = es.connection_id
            JOIN ledgerbridge_system.sources AS s ON s.id = c.source_id
            WHERE es.entity_id = e.id ORDER BY es.id LIMIT 1)"""


def _data_health(with_source: bool) -> str:
    source = f", {SOURCE_NAME} AS source_name" if with_source else ""
    return f"""CREATE OR REPLACE VIEW ledgerbridge_reporting.v_data_health AS
    SELECT e.id AS entity_id,
           {LAST_SYNC} AS last_sync_at,
           {LATEST_VALIDATION.format(column="status")} AS validation_status,
           {LATEST_VALIDATION.format(column="as_of")} AS validated_as_of,
           {LATEST_VALIDATION.format(column="started_at")} AS validated_at{source}
    FROM ledgerbridge_accounting.entities AS e"""


def upgrade() -> None:
    op.add_column(
        "entity_sources", sa.Column("source_checked_at", TIMESTAMP, nullable=True), schema=ACCOUNTING
    )
    op.add_column(
        "entity_sources", sa.Column("source_loaded", sa.Boolean(), nullable=True), schema=ACCOUNTING
    )
    op.add_column(
        "entity_sources",
        sa.Column(
            "source_checked_by", sa.Enum("sync", "entity_check", name="source_check"), nullable=True
        ),
        schema=ACCOUNTING,
    )
    op.execute(_data_health(with_source=True))


def downgrade() -> None:
    op.execute(_data_health(with_source=False))
    for column in ("source_checked_by", "source_loaded", "source_checked_at"):
        op.drop_column("entity_sources", column, schema=ACCOUNTING)
