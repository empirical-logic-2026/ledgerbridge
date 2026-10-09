"""The seeded reference data is in the test database (./dev.ps1 up)."""

import pytest
from alembic import command
from sqlalchemy import text

from core.db import get_engine
from core.models.schemas import ACCOUNTING
from tests.test_migrations_integration import _config
from tests.test_standard_accounts import seeded_accounts

pytestmark = pytest.mark.integration


def test_reference_data_is_seeded() -> None:
    command.upgrade(_config(), "head")
    with get_engine("report").connect() as conn:
        assert conn.scalar(text(f"SELECT name FROM {ACCOUNTING}.currencies WHERE code='INR'"))
        total = conn.scalar(text(f"SELECT COUNT(*) FROM {ACCOUNTING}.standard_accounts"))
        orphans = conn.scalar(
            text(
                f"SELECT COUNT(*) FROM {ACCOUNTING}.standard_accounts c "
                f"LEFT JOIN {ACCOUNTING}.standard_accounts p ON p.id = c.parent_id "
                "WHERE c.parent_id IS NOT NULL AND p.id IS NULL"
            )
        )
    assert total == len(seeded_accounts())
    assert orphans == 0
