import os
from collections.abc import Iterator

# No heartbeat threads in tests: SQLite stand-ins share one connection (tests/test_runs.py
# covers the heartbeat itself).
os.environ.setdefault("SYNC_HEARTBEAT_SEC", "0")
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from connectors.tally.connector import TallyConnector
from connectors.tally.fixtures import DEFAULT_DIR, FixtureTransport
from core.models import Base
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.models.base import utcnow
from core.models.schemas import ALL
from tests.test_standard_accounts import seeded_accounts
from workers.extract import get_or_create_connection
from workers.sync import run_sync

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def engine() -> Iterator[Engine]:
    """In-memory SQLite with the four databases (ADR-016) attached, standing in for MySQL."""
    # check_same_thread off: API tests reach this one connection from the TestClient thread.
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def _attach(dbapi_connection, _record) -> None:  # noqa: ANN001
        for schema in ALL:
            dbapi_connection.execute(f"ATTACH DATABASE ':memory:' AS {schema}")

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


# --- the recorded LedgerBridge Test Co, synced into SQLite (M3, M4) ---------------------

COMPANY = "LedgerBridge Test Co"


@pytest.fixture
def db(session: Session) -> Session:
    """SQLite stand-in with the reference data of migration 0003."""
    now = utcnow()
    session.add(A.Currency(code="INR", name="Indian Rupee", created_at=now, updated_at=now))
    ids: dict[str, int] = {}
    for order, (code, parent, name, nature, statement, line, cash) in enumerate(seeded_accounts()):
        account = A.StandardAccount(
            parent_id=ids.get(parent) if parent else None,
            code=code,
            name=name,
            nature=nature,
            statement=statement,
            statement_line=line,
            cash_flow_class=cash,
            sort_order=order,
            created_at=now,
            updated_at=now,
        )
        session.add(account)
        session.flush()
        ids[code] = account.id
    session.commit()
    return session


@pytest.fixture
def connector() -> TallyConnector:
    return TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=FixtureTransport(DEFAULT_DIR)
    )


@pytest.fixture
def synced(
    db: Session, connector: TallyConnector, monkeypatch: pytest.MonkeyPatch
) -> Iterator[S.Connection]:
    monkeypatch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )
    connection = get_or_create_connection(db, "tally-test", "tally")
    db.commit()
    result = run_sync(db, connection, connector, [COMPANY])
    assert result.status == "succeeded", result.error
    assert result.failed == 0
    # Only the two Central Tax ledgers come back with an empty GST duty head.
    assert sorted(w.split(":")[0] for w in result.warnings) == ["Input CGST", "Output CGST"]
    assert all("assumed Central Tax" in w for w in result.warnings)
    yield connection
