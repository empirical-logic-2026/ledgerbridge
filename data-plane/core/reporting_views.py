"""The reporting views the dashboard API reads, as SQLAlchemy tables (read-only).

They are created by migrations (0024: `v_group_ancestors`, `v_data_health`, extended in
0025), not by the
models, so they are declared on their own metadata: Alembic's model comparison never sees
them.
"""

from sqlalchemy import Column, Date, DateTime, Integer, MetaData, String, Table

from core.models.schemas import REPORTING

_views = MetaData()

# Each account group with every group above it, itself included (depth 0).
GROUP_ANCESTORS = Table(
    "v_group_ancestors",
    _views,
    Column("entity_id", Integer),
    Column("group_id", Integer),
    Column("ancestor_id", Integer),
    Column("depth", Integer),
    schema=REPORTING,
)

# Per entity: the last successful sync and the latest validation (dates and statuses only).
DATA_HEALTH = Table(
    "v_data_health",
    _views,
    Column("entity_id", Integer),
    Column("last_sync_at", DateTime),
    Column("validation_status", String(16)),
    Column("validated_as_of", Date),
    Column("validated_at", DateTime),
    Column("source_name", String(255)),  # migration 0025
    schema=REPORTING,
)
