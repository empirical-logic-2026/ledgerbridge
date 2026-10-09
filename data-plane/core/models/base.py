"""Declarative base, shared column types and mixins (schema.md Sections 1 and 9)."""

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from core.models.schemas import SYSTEM

# BIGINT UNSIGNED on MySQL; plain INTEGER on SQLite so unit tests get autoincrement.
Id = BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql").with_variant(Integer, "sqlite")
# DATETIME(6), stored as naive UTC.
Timestamp = DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
LongText = Text().with_variant(mysql.LONGTEXT(), "mysql")
VarBinary = LargeBinary().with_variant(mysql.VARBINARY(4096), "mysql")
Money = Numeric(20, 4)  # amounts; never float (schema.md Section 1)
Rate = Numeric(20, 6)  # quantities, rates, percentages
FxRate = Numeric(20, 8)  # exchange rates
TinyInt = Integer().with_variant(mysql.TINYINT(), "mysql")
SmallInt = Integer().with_variant(mysql.SMALLINT(), "mysql")

ORIGINS = ("live", "backup", "file", "manual")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def flag(default: bool = False) -> Mapped[bool]:
    """BOOLEAN NOT NULL with a server-side default (schema.md Section 9)."""
    server_default = true() if default else false()
    return mapped_column(Boolean, nullable=False, default=default, server_default=server_default)


def name_column(length: int = 255) -> Mapped[str]:
    return mapped_column(String(length), nullable=False)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow, onupdate=utcnow)


class SourceTrackingMixin:
    """The [SRC] columns of schema.md Section 1.1, for canonical tables fed by a source."""

    @declared_attr
    def connection_id(cls) -> Mapped[int]:  # noqa: N805
        return mapped_column(Id, ForeignKey(f"{SYSTEM}.connections.id"), nullable=False)

    source_key: Mapped[str] = mapped_column(String(191), nullable=False)
    source_alter_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    origin: Mapped[str] = mapped_column(Enum(*ORIGINS, name="origin"), nullable=False)

    @declared_attr
    def import_batch_id(cls) -> Mapped[int | None]:  # noqa: N805
        return mapped_column(Id, ForeignKey(f"{SYSTEM}.import_batches.id"), nullable=True)

    # No foreign key: raw_records will be partitioned, and MySQL forbids FKs to partitioned
    # tables (schema.md Section 9).
    raw_record_id: Mapped[int | None] = mapped_column(Id, nullable=True)
    is_deleted: Mapped[bool] = flag()


def src_table_args(table: str, schema: str, *extra: object) -> tuple[object, ...]:
    """Table args for an [SRC] table: unique (connection_id, source_key) plus a lineage index."""
    return (
        UniqueConstraint("connection_id", "source_key", name=f"uq_{table}_source"),
        Index(f"ix_{table}_raw_record", "raw_record_id"),
        *extra,
        {"schema": schema},
    )
