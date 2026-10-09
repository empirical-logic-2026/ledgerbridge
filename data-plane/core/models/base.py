"""Declarative base, shared column types and timestamp columns (schema.md Section 1)."""

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Integer, LargeBinary, Text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# BIGINT UNSIGNED on MySQL; plain INTEGER on SQLite so unit tests get autoincrement.
Id = BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql").with_variant(Integer, "sqlite")
# DATETIME(6), stored as naive UTC.
Timestamp = DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
LongText = Text().with_variant(mysql.LONGTEXT(), "mysql")
VarBinary = LargeBinary().with_variant(mysql.VARBINARY(4096), "mysql")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow, onupdate=utcnow)
