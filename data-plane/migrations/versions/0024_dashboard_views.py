"""Reporting views for the dashboard (D1; ADR-049).

- `v_group_ancestors`: each account group with every group above it (itself included, depth
  0), so a filter on a group also finds the ledgers of its sub-groups;
- `v_data_health`: per entity, the last successful sync of its connections and its latest
  validation. The dashboard reads the databases as `report_ro`, which has no access to
  `ledgerbridge_system`; the view (run with its definer's rights) shows only these dates
  and statuses.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE_GROUP_ANCESTORS = """CREATE VIEW ledgerbridge_reporting.v_group_ancestors AS
    WITH RECURSIVE up (entity_id, group_id, ancestor_id, parent_id, depth) AS (
        SELECT g.entity_id, g.id, g.id, g.parent_id, 0
        FROM ledgerbridge_accounting.account_groups AS g
        UNION ALL
        SELECT u.entity_id, u.group_id, p.id, p.parent_id, u.depth + 1
        FROM up AS u
        JOIN ledgerbridge_accounting.account_groups AS p ON p.id = u.parent_id
        WHERE u.depth < 64
    )
    SELECT entity_id, group_id, ancestor_id, depth FROM up"""

CREATE_DATA_HEALTH = """CREATE VIEW ledgerbridge_reporting.v_data_health AS
    SELECT e.id AS entity_id,
           (SELECT MAX(r.finished_at)
            FROM ledgerbridge_system.sync_runs AS r
            JOIN ledgerbridge_accounting.entity_sources AS es
              ON es.connection_id = r.connection_id
            WHERE es.entity_id = e.id AND r.status = 'succeeded'
              AND r.run_type IN ('full', 'incremental')) AS last_sync_at,
           (SELECT v.status FROM ledgerbridge_system.validation_runs AS v
            WHERE v.entity_id = e.id ORDER BY v.id DESC LIMIT 1) AS validation_status,
           (SELECT v.as_of FROM ledgerbridge_system.validation_runs AS v
            WHERE v.entity_id = e.id ORDER BY v.id DESC LIMIT 1) AS validated_as_of,
           (SELECT v.started_at FROM ledgerbridge_system.validation_runs AS v
            WHERE v.entity_id = e.id ORDER BY v.id DESC LIMIT 1) AS validated_at
    FROM ledgerbridge_accounting.entities AS e"""


def upgrade() -> None:
    op.execute(CREATE_GROUP_ANCESTORS)
    op.execute(CREATE_DATA_HEALTH)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS ledgerbridge_reporting.v_data_health")
    op.execute("DROP VIEW IF EXISTS ledgerbridge_reporting.v_group_ancestors")
