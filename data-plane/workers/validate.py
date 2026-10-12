"""Validation after sync runs, and the alerts that follow (VAL-001, VAL-002, SYN-006).

`after_run` is called by the worker and the CLI after every sync or deletion check:
- a failed run raises a `sync_failed` / `deletion_check_failed` alert; a successful one
  resolves it and validates every entity in the run;
- a validation with errors raises a `validation_failed` alert for that entity; a passing
  one resolves it (ADR-019).
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from connectors.base import Connector, SourceBalances
from core.alerts import raise_alert, resolve_alert
from core.config import get_settings
from core.errors import short_error
from core.models import Connection
from core.validation import ValidationReport, Validator
from workers.entities import select_entities
from workers.sync import DELETION_CHECK, Progress, SyncResult, entity_ids_for

logger = logging.getLogger(__name__)


def tolerance_for(connection: Connection) -> Decimal:
    """VALIDATION_TOLERANCE, or connections.config.validation_tolerance (default 0, exact)."""
    configured = connection.config.get("validation_tolerance")
    return Decimal(
        str(configured if configured is not None else get_settings().validation_tolerance)
    )


def run_validation(
    session: Session,
    connection: Connection,
    connector: Connector,
    entity_names: Sequence[str] | None = None,
    as_of: date | None = None,
    sync_run_id: int | None = None,
    entity_keys: Sequence[str] | None = None,
    progress: Progress | None = None,
) -> list[ValidationReport]:
    """Validates each synced entity of the connection as of a date (default today)."""
    as_of = as_of or date.today()
    entities = select_entities(connector, connection, entity_names, entity_keys)
    entity_ids = entity_ids_for(session, connection.id, [e.key for e in entities])
    reports = []
    for number, entity in enumerate(entities, start=1):
        entity_id = entity_ids.get(entity.key)
        if entity_id is None:
            continue  # never synced: nothing to validate
        if progress:
            progress(f"entity {number} of {len(entities)}: validating as of {as_of}")
        source: SourceBalances | Exception | None = None
        if hasattr(connector, "closing_balances"):
            try:
                source = connector.closing_balances(entity, as_of)
            except Exception as exc:  # noqa: BLE001 - recorded as a closing_unavailable issue
                source = exc
        report = Validator(session, entity_id, as_of, tolerance_for(connection), connection.id).run(
            source, sync_run_id
        )
        _alert(session, connection, report)
        # Counts and codes only: never names or amounts in logs.
        logger.info(
            "Validation run %s (entity %s): %s, %s passed, %s failed",
            report.validation_run_id,
            entity_id,
            report.status,
            report.checks_passed,
            report.checks_failed,
        )
        reports.append(report)
    return reports


def _alert(session: Session, connection: Connection, report: ValidationReport) -> None:
    if report.status == "passed":
        resolve_alert(session, "validation_failed", connection.id, entity_id=report.entity_id)
        return
    codes = ", ".join(f"{code} {n}" for code, n in sorted(report.failed_by_code.items()))
    raise_alert(
        session,
        "validation_failed",
        connection.id,
        f"Validation as of {report.as_of}: {report.checks_failed} checks failed ({codes}).",
        entity_id=report.entity_id,
        validation_run_id=report.validation_run_id,
    )


@dataclass
class AfterRun:
    """What followed a sync run. The run's own status never depends on validation: a run
    whose fetch and transform succeeded stays `succeeded` even if validation fails or
    can't run (pilot run, 2026-10-12)."""

    reports: list[ValidationReport] = field(default_factory=list)
    validation_error: str | None = None  # why validation couldn't run (short, no SQL)

    @property
    def validation_status(self) -> str:
        if self.validation_error:
            return "failed"
        if not self.reports:
            return "not run"
        return "failed" if any(r.status == "failed" for r in self.reports) else "passed"


def alert_for_run(session: Session, connection: Connection, result: SyncResult) -> bool:
    """Raises or resolves the run's own alert. True if the run succeeded."""
    kind = "deletion_check_failed" if result.run_type == DELETION_CHECK else "sync_failed"
    if result.status != "succeeded":
        raise_alert(
            session,
            kind,
            connection.id,
            f"{result.run_type} run {result.sync_run_id} failed; see sync_runs.error_summary.",
            sync_run_id=result.sync_run_id,
        )
        return False
    resolve_alert(session, kind, connection.id)
    return True


def validate_after(
    session: Session,
    connection: Connection,
    connector: Connector,
    result: SyncResult,
    progress: Progress | None = None,
) -> AfterRun:
    """Validates the entities of a succeeded run, found by key. A validation that can't run
    is recorded as a failed validation (and alerted), never as a failed sync."""
    if not result.entity_keys:
        return AfterRun()
    try:
        reports = run_validation(
            session,
            connection,
            connector,
            sync_run_id=result.sync_run_id,
            entity_keys=result.entity_keys,
            progress=progress,
        )
    except Exception as exc:  # noqa: BLE001 - recorded as a failed validation, not a failed sync
        session.rollback()
        error = short_error(exc, redact=True)
        raise_alert(
            session,
            "validation_failed",
            connection.id,
            f"Validation after {result.run_type} run {result.sync_run_id} couldn't run: {error}",
            sync_run_id=result.sync_run_id,
        )
        logger.error("Validation after sync run %s couldn't run: %s", result.sync_run_id, error)
        return AfterRun(validation_error=error)
    return AfterRun(reports)


def after_run(
    session: Session,
    connection: Connection,
    connector: Connector,
    result: SyncResult,
    progress: Progress | None = None,
) -> AfterRun:
    """Alerts for the run, then validation of its entities if it succeeded."""
    if not alert_for_run(session, connection, result):
        return AfterRun()
    return validate_after(session, connection, connector, result, progress)
