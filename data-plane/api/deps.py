"""Shared FastAPI dependencies."""

from collections.abc import Iterator

from sqlalchemy.orm import Session

from core.db import get_engine


def get_session() -> Iterator[Session]:
    """A database session as the app_rw user, closed after the request."""
    with Session(get_engine()) as session:
        yield session


def get_report_session() -> Iterator[Session]:
    """A read-only session as the report_ro user (schema.md 2.1): the dashboard API
    (/api/v1) reads through it, so it can't change anything (ADR-049)."""
    with Session(get_engine("report")) as session:
        yield session
