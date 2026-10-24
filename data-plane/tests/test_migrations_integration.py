"""Runs Alembic against the test stack's MySQL as the migrator (./dev.ps1 up)."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

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


def _clear_synced_data() -> None:
    """Empties every table except the reference data migrations seed, so the downgrade can
    run on a test database that holds synced data. Test environment only: this resets it."""
    reference = {"standard_accounts", "currencies"}
    with get_engine("migrator").begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in reversed(Base.metadata.sorted_tables):
            if table.name not in reference:
                conn.execute(table.delete())
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


def test_upgrade_downgrade_upgrade_creates_every_model_table() -> None:
    command.upgrade(_config(), "head")
    assert _tables() == _model_tables() | {f"{SYSTEM}.alembic_version"}
    _clear_synced_data()
    command.downgrade(_config(), "base")
    assert _tables() == {f"{SYSTEM}.alembic_version"}
    command.upgrade(_config(), "head")
    assert _tables() == _model_tables() | {f"{SYSTEM}.alembic_version"}


def test_expected_table_counts() -> None:
    """The reporting database holds only `statement_lines` (migration 0017, ADR-040); its
    views aren't tables. `currency_sources` added in migration 0020 (ADR-046)."""
    command.upgrade(_config(), "head")
    tables = _tables()
    count = {schema: sum(t.startswith(f"{schema}.") for t in tables) for schema in ALL}
    assert count == {SOURCE: 1, ACCOUNTING: 29, REPORTING: 1, SYSTEM: 26}  # 25 + alembic_version
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


def test_the_open_differences_view_pairs_taken_and_computed_lines() -> None:
    """v_statement_open_differences (0018, ADR-043): a line taken from the source beside
    ours computed, listed only where they differ, with the debit and credit gaps."""
    command.upgrade(_config(), "head")
    insert = text(
        f"INSERT INTO {REPORTING}.statement_lines (entity_id, as_of, statement, figures, "
        "line_no, section, label, match_key, level, amount, debit, credit, refreshed_at, "
        "created_at, updated_at) VALUES (999999, '2022-05-02', :statement, 'ours', :n, NULL, "
        ":label, :key, :level, :amount, :debit, :credit, NOW(), NOW(), NOW())"
    )
    rows = [
        ("trial_balance", 1, "Current Assets (taken from the source)", "main", 90, 100, 10),
        ("trial_balance", 2, "Current Assets (computed)", "detail", 85, 95, 10),
        ("balance_sheet", 1, "Current Assets (taken from the source)", "main", 90, None, None),
        ("balance_sheet", 2, "Current Assets (computed)", "detail", 90, None, None),
    ]
    with get_engine("migrator").connect() as conn:
        transaction = conn.begin()
        try:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for statement, n, label, level, amount, debit, credit in rows:
                conn.execute(insert, {
                    "statement": statement, "n": n, "label": label, "key": "current assets",
                    "level": level, "amount": amount, "debit": debit, "credit": credit,
                })  # fmt: skip
            found = conn.execute(
                text(
                    f"SELECT statement, difference, debit_difference, credit_difference FROM "
                    f"{REPORTING}.v_statement_open_differences WHERE entity_id = 999999"
                )
            ).all()
        finally:
            transaction.rollback()
    assert [(s, float(d), float(dd), float(cd)) for s, d, dd, cd in found] == [
        ("trial_balance", 5.0, 5.0, 0.0)  # the balance sheet line equal: not open
    ]
