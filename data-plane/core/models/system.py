"""`ledgerbridge_system`: integration, validation, security, audit and configuration
(schema.md Section 5; types per Section 9)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    JSON,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import (
    Base,
    Id,
    Money,
    Timestamp,
    TimestampMixin,
    VarBinary,
    flag,
    name_column,
)
from core.models.schemas import ACCOUNTING, SYSTEM

CONNECTION_STATUSES = ("active", "paused", "error")
RUN_TYPES = ("incremental", "full", "import")
RUN_STATUSES = ("running", "succeeded", "failed")
_S = {"schema": SYSTEM}


# --- 5.1 Integration -------------------------------------------------------------------


class Source(TimestampMixin, Base):
    """A registered connector type, e.g. `tally`."""

    __tablename__ = "sources"
    __table_args__ = _S

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    connector_version: Mapped[str] = mapped_column(String(32))


class Agent(TimestampMixin, Base):
    """Connector agent near an on-premise source (SYN-004)."""

    __tablename__ = "agents"
    __table_args__ = _S

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    cert_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("active", "disabled", name="agent_status"), default="active"
    )


class Connection(TimestampMixin, Base):
    """One configured connection to a source system."""

    __tablename__ = "connections"
    __table_args__ = _S

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Id, ForeignKey(f"{SYSTEM}.sources.id"))
    name: Mapped[str] = mapped_column(String(255), unique=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Encrypted at application level (CON-009); NULL for sources without credentials.
    credentials_enc: Mapped[bytes | None] = mapped_column(VarBinary, nullable=True)
    agent_id: Mapped[int | None] = mapped_column(
        Id, ForeignKey(f"{SYSTEM}.agents.id", name="fk_connections_agent"), nullable=True
    )
    sync_interval_sec: Mapped[int] = mapped_column(Integer, default=300)
    status: Mapped[str] = mapped_column(
        Enum(*CONNECTION_STATUSES, name="connection_status"), default="active"
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class SyncMarker(TimestampMixin, Base):
    """Last AlterID / timestamp per connection, source entity and object type."""

    __tablename__ = "sync_markers"
    __table_args__ = _S

    connection_id: Mapped[int] = mapped_column(
        Id, ForeignKey(f"{SYSTEM}.connections.id"), primary_key=True
    )
    source_entity_key: Mapped[str] = mapped_column(String(191), primary_key=True)
    object_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    marker_value: Mapped[str] = mapped_column(String(191))


class SyncRun(TimestampMixin, Base):
    """One extraction or sync run (SYN-005)."""

    __tablename__ = "sync_runs"
    __table_args__ = _S

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    connection_id: Mapped[int] = mapped_column(Id, ForeignKey(f"{SYSTEM}.connections.id"))
    run_type: Mapped[str] = mapped_column(Enum(*RUN_TYPES, name="sync_run_type"))
    status: Mapped[str] = mapped_column(Enum(*RUN_STATUSES, name="sync_run_status"))
    started_at: Mapped[datetime] = mapped_column(Timestamp)
    finished_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    records_received: Mapped[int] = mapped_column(Integer, default=0)
    records_failed: Mapped[int] = mapped_column(Integer, default=0)
    # Exception type and message only; never payloads or accounting values.
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class ImportBatch(TimestampMixin, Base):
    """A backup or file import (IMP-003, IMP-004)."""

    __tablename__ = "import_batches"
    __table_args__ = _S

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    connection_id: Mapped[int] = mapped_column(Id, ForeignKey(f"{SYSTEM}.connections.id"))
    kind: Mapped[str] = mapped_column(Enum("backup", "file", name="import_kind"))
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    period_from: Mapped[date | None] = mapped_column(nullable=True)
    period_to: Mapped[date | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("pending", "running", "succeeded", "failed", name="import_status"),
        default="pending",
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class FileLayout(TimestampMixin, Base):
    """Saved CSV/TXT column mapping (CON-003)."""

    __tablename__ = "file_layouts"
    __table_args__ = (UniqueConstraint("connection_id", "name", name="uq_file_layouts_name"), _S)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    connection_id: Mapped[int] = mapped_column(Id, ForeignKey(f"{SYSTEM}.connections.id"))
    name: Mapped[str] = name_column()
    column_mapping: Mapped[dict[str, Any]] = mapped_column(JSON)


# --- 5.2 Validation --------------------------------------------------------------------


class ValidationRun(TimestampMixin, Base):
    __tablename__ = "validation_runs"
    __table_args__ = _S

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    sync_run_id: Mapped[int | None] = mapped_column(
        Id, ForeignKey(f"{SYSTEM}.sync_runs.id"), nullable=True
    )
    import_batch_id: Mapped[int | None] = mapped_column(
        Id, ForeignKey(f"{SYSTEM}.import_batches.id"), nullable=True
    )
    entity_id: Mapped[int] = mapped_column(Id, ForeignKey(f"{ACCOUNTING}.entities.id"))
    started_at: Mapped[datetime] = mapped_column(Timestamp)
    status: Mapped[str] = mapped_column(
        Enum("running", "passed", "failed", name="validation_status"), default="running"
    )
    checks_passed: Mapped[int] = mapped_column(Integer, default=0)
    checks_failed: Mapped[int] = mapped_column(Integer, default=0)


class ValidationIssue(TimestampMixin, Base):
    __tablename__ = "validation_issues"
    __table_args__ = _S

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    validation_run_id: Mapped[int] = mapped_column(Id, ForeignKey(f"{SYSTEM}.validation_runs.id"))
    check_code: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(Enum("error", "warning", "info", name="issue_severity"))
    object_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expected_value: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    actual_value: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    message: Mapped[str] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)


# --- 5.3 Security ----------------------------------------------------------------------


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = _S

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)  # same ID as the control plane
    email: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = name_column()
    status: Mapped[str] = mapped_column(
        Enum("active", "disabled", "locked", name="user_status"), default="active"
    )
    # Used only when AUTH_MODE=local (ADR-010).
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Role(TimestampMixin, Base):
    __tablename__ = "roles"
    __table_args__ = _S

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = name_column()
    is_system: Mapped[bool] = flag()


class Permission(TimestampMixin, Base):
    __tablename__ = "permissions"
    __table_args__ = _S

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)


class RolePermission(TimestampMixin, Base):
    __tablename__ = "role_permissions"
    __table_args__ = _S

    role_id: Mapped[int] = mapped_column(Id, ForeignKey(f"{SYSTEM}.roles.id"), primary_key=True)
    permission_id: Mapped[int] = mapped_column(
        Id, ForeignKey(f"{SYSTEM}.permissions.id"), primary_key=True
    )


class UserRole(TimestampMixin, Base):
    __tablename__ = "user_roles"
    __table_args__ = _S

    user_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey(f"{SYSTEM}.users.id"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(Id, ForeignKey(f"{SYSTEM}.roles.id"), primary_key=True)


class UserEntityAccess(TimestampMixin, Base):
    """NULL branch = all branches of the entity."""

    __tablename__ = "user_entity_access"
    __table_args__ = (
        UniqueConstraint("user_id", "entity_id", "branch_id", name="uq_user_entity_access"),
        _S,
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey(f"{SYSTEM}.users.id"))
    entity_id: Mapped[int] = mapped_column(Id, ForeignKey(f"{ACCOUNTING}.entities.id"))
    branch_id: Mapped[int | None] = mapped_column(
        Id, ForeignKey(f"{ACCOUNTING}.branches.id"), nullable=True
    )


class MaskingRule(TimestampMixin, Base):
    __tablename__ = "masking_rules"
    __table_args__ = _S

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    role_id: Mapped[int] = mapped_column(Id, ForeignKey(f"{SYSTEM}.roles.id"))
    target: Mapped[str] = mapped_column(String(64))  # e.g. party.name, party.pan
    mask_type: Mapped[str] = mapped_column(Enum("hide", "partial", "hash", name="mask_type"))


# --- 5.4 Audit and AI log --------------------------------------------------------------


class AuditLog(TimestampMixin, Base):
    """Append-only (AUD-002). user_id has no foreign key: the log outlives users."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_occurred_at", "occurred_at"),
        Index("ix_audit_log_user_id", "user_id"),
        _S,
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(Timestamp)
    user_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    object_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(
        Id, ForeignKey(f"{ACCOUNTING}.entities.id"), nullable=True
    )
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)


class AiQueryLog(TimestampMixin, Base):
    """One row per AI question. The per-model-call log (AI-018) is designed in M8."""

    __tablename__ = "ai_query_log"
    __table_args__ = (Index("ix_ai_query_log_user_created", "user_id", "created_at"), _S)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True)
    question: Mapped[str] = mapped_column(Text)
    generated_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("succeeded", "failed", "refused", name="ai_query_status")
    )
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)


# --- 5.5 Configuration -----------------------------------------------------------------


class KpiDefinition(TimestampMixin, Base):
    """Business health indicators (RPT-002)."""

    __tablename__ = "kpi_definitions"
    __table_args__ = _S

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = name_column()
    formula_view: Mapped[str] = mapped_column(String(128))
    good_threshold: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    bad_threshold: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    direction: Mapped[str] = mapped_column(
        Enum("higher_better", "lower_better", name="kpi_direction")
    )


class Setting(TimestampMixin, Base):
    __tablename__ = "settings"
    __table_args__ = _S

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
