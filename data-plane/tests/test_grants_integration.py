"""Each MySQL user has exactly the rights in schema.md 2.1 (test stack: ./dev.ps1 up)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from core.db import get_engine
from core.models.schemas import ACCOUNTING, REPORTING, SOURCE, SYSTEM

pytestmark = pytest.mark.integration

DENIED = (OperationalError, ProgrammingError)  # MySQL 1142/1044: command or database denied


def _run(role: str, sql: str) -> None:
    with get_engine(role).connect() as conn:  # type: ignore[arg-type]
        conn.execute(text(sql))
        conn.rollback()


@pytest.mark.parametrize("database", [SOURCE, ACCOUNTING, SYSTEM])
def test_ai_user_cannot_read_anything_but_reporting(database: str) -> None:
    table = {
        SOURCE: "raw_records",
        ACCOUNTING: "standard_accounts",
        SYSTEM: "users",
    }[database]
    with pytest.raises(DENIED):
        _run("ai", f"SELECT 1 FROM {database}.{table} LIMIT 1")


def test_ai_user_can_use_reporting() -> None:
    with get_engine("ai").connect() as conn:
        assert conn.scalar(text("SELECT DATABASE()")) == REPORTING
        grants = [row[0] for row in conn.execute(text("SHOW GRANTS"))]
    granted_on = " ".join(g for g in grants if "USAGE" not in g)
    assert f"`{REPORTING}`" in granted_on
    for other in (SOURCE, ACCOUNTING, SYSTEM):
        assert f"`{other}`" not in granted_on
    assert all("SELECT" in g and "INSERT" not in g for g in grants if "USAGE" not in g)


def test_report_user_reads_accounting_but_cannot_write_or_read_system() -> None:
    _run("report", f"SELECT 1 FROM {ACCOUNTING}.standard_accounts LIMIT 1")
    with pytest.raises(DENIED):
        _run("report", f"UPDATE {ACCOUNTING}.currencies SET name = name WHERE code = 'INR'")
    with pytest.raises(DENIED):
        _run("report", f"SELECT 1 FROM {SYSTEM}.users LIMIT 1")


def test_app_user_reads_and_writes_but_cannot_change_schema() -> None:
    _run("app", f"UPDATE {ACCOUNTING}.currencies SET name = name WHERE code = 'INR'")
    with pytest.raises(DENIED):
        _run("app", f"CREATE TABLE {SYSTEM}.lb_grant_probe (id INT)")
    with pytest.raises(DENIED):
        _run("app", f"DROP TABLE {SYSTEM}.settings")
