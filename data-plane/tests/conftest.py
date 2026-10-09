from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core.models import Base
from core.models.schemas import ALL

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def engine() -> Iterator[Engine]:
    """In-memory SQLite with the four databases (ADR-016) attached, standing in for MySQL."""
    engine = create_engine("sqlite://", poolclass=StaticPool)

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
