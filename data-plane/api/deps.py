"""Shared FastAPI dependencies."""

from collections.abc import Iterator

from sqlalchemy.orm import Session

from core.db import get_engine


def get_session() -> Iterator[Session]:
    """A database session as the app_rw user, closed after the request."""
    with Session(get_engine()) as session:
        yield session
