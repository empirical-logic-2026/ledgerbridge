"""Runs Alembic against the test stack's MySQL (./deploy/stack.ps1 -Env test up -d)."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from core.db import get_engine

pytestmark = pytest.mark.integration

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def _tables() -> set[str]:
    inspector = inspect(get_engine())
    return {
        f"{schema}.{table}"
        for schema in ("raw", "app")
        for table in inspector.get_table_names(schema=schema)
    }


def test_upgrade_downgrade_upgrade() -> None:
    config = Config(str(ALEMBIC_INI))
    command.upgrade(config, "head")
    assert {"raw.raw_records", "app.sources", "app.connections", "app.sync_runs"} <= _tables()
    command.downgrade(config, "base")
    assert _tables() <= {"app.alembic_version"}
    command.upgrade(config, "head")
    assert "raw.raw_records" in _tables()
