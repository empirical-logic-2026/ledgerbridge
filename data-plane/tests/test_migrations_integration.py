"""Runs Alembic against the test stack's MySQL as the migrator (./dev.ps1 up)."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from core.db import get_engine
from core.models import Base
from core.models.schemas import ACCOUNTING, ALL, REPORTING, SOURCE, SYSTEM

pytestmark = pytest.mark.integration

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def _config() -> Config:
    return Config(str(ALEMBIC_INI))


def _tables() -> set[str]:
    inspector = inspect(get_engine("migrator"))
    return {
        f"{schema}.{table}" for schema in ALL for table in inspector.get_table_names(schema=schema)
    }


def _model_tables() -> set[str]:
    return {f"{table.schema}.{table.name}" for table in Base.metadata.sorted_tables}


def test_upgrade_downgrade_upgrade_creates_every_model_table() -> None:
    command.upgrade(_config(), "head")
    assert _tables() == _model_tables() | {f"{SYSTEM}.alembic_version"}
    command.downgrade(_config(), "base")
    assert _tables() == {f"{SYSTEM}.alembic_version"}
    command.upgrade(_config(), "head")
    assert _tables() == _model_tables() | {f"{SYSTEM}.alembic_version"}


def test_expected_table_counts_and_empty_reporting_database() -> None:
    command.upgrade(_config(), "head")
    tables = _tables()
    count = {schema: sum(t.startswith(f"{schema}.") for t in tables) for schema in ALL}
    assert count == {SOURCE: 1, ACCOUNTING: 25, REPORTING: 0, SYSTEM: 21}  # 20 + alembic_version
    assert f"{ACCOUNTING}.bank_statement_lines" not in tables  # phase 2


def test_models_and_database_match() -> None:
    """Fails if a model and the migrations disagree (alembic autogenerate diff)."""
    command.upgrade(_config(), "head")
    command.check(_config())


def test_voucher_children_cascade_on_delete() -> None:
    inspector = inspect(get_engine("migrator"))
    cascading = {
        (table, fk["referred_table"])
        for table in (
            "voucher_lines",
            "bill_allocations",
            "line_cost_allocations",
            "line_dimensions",
            "inventory_lines",
            "tax_lines",
        )  # fmt: skip
        for fk in inspector.get_foreign_keys(table, schema=ACCOUNTING)
        if fk.get("options", {}).get("ondelete") == "CASCADE"
    }
    assert cascading == {
        ("voucher_lines", "vouchers"),
        ("bill_allocations", "voucher_lines"),
        ("line_cost_allocations", "voucher_lines"),
        ("line_dimensions", "voucher_lines"),
        ("inventory_lines", "vouchers"),
        ("tax_lines", "vouchers"),
        ("tax_lines", "voucher_lines"),
    }
