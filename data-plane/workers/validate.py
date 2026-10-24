"""Validation after sync runs, and the alerts that follow (VAL-001, VAL-002, SYN-006).

`after_run` is called by the worker and the CLI after every sync or deletion check:
- a failed run raises a `sync_failed` / `deletion_check_failed` alert; a successful one
  resolves it and validates every entity in the run;
- a validation with errors raises a `validation_failed` alert for that entity; a passing
  one resolves it (ADR-019).
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from connectors.base import Connector, SourceBalances, SourceControls, SourceEntity
from core.alerts import raise_alert, resolve_alert
from core.config import get_settings
from core.dates import EVERY_DAY, DateRule, date_rule
from core.errors import short_error
from core.models import Connection
from core.models.accounting import Entity
from core.validation import ValidationReport, Validator, financial_year_ends
from workers.entities import ExpectedEntityNotLoadedError, Labels, ensure_loaded, select_entities
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
    thorough: bool = False,
) -> list[ValidationReport]:
    """Validates each synced entity of the connection as of a date (default today).

    `thorough` also compares the source's own controls (VAL-005 to VAL-008): voucher counts
    per month and type, stock quantities, bill-wise outstanding and the balances at every
    year end. They take more requests to the source, so scheduled incremental syncs skip
    them; `validate`, full syncs and `transform retry` run them."""
    asked = as_of or date.today()
    entities = select_entities(connector, connection, entity_names, entity_keys)
    rule = date_rule(connector, entities[0]) if entities else EVERY_DAY
    as_of = rule.on_or_before(asked)  # Educational mode: a reliable date (core/dates.py)
    entity_ids = entity_ids_for(session, connection.id, [e.key for e in entities])
    labels = Labels(session, connection)
    reports = []
    for entity in entities:
        entity_id = entity_ids.get(entity.key)
        if entity_id is None:
            continue  # never synced: nothing to validate
        label = labels.for_key(entity.key)
        if progress:
            depth = " (thorough: counts, stock, bills, year ends)" if thorough else ""
            dates = (
                f"; {rule.describe()}, so as of {as_of} instead of {asked}"
                if as_of != asked
                else (f"; {rule.describe()}" if rule.restricted else "")
            )
            progress(f"{label}: validating as of {as_of}{depth}{dates}")
        ensure_loaded(connector, entity)  # LB-SYNC-011: never compare another company
        source: SourceBalances | Exception | None = _read(
            connector, "closing_balances", entity, as_of
        )
        controls = None
        if thorough:
            controls = source_controls(
                connector, entity, session.get_one(Entity, entity_id), as_of, rule, progress
            )
        ensure_loaded(connector, entity)  # still the same company after reading
        report = Validator(session, entity_id, as_of, tolerance_for(connection), connection.id).run(
            source, sync_run_id, controls
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


def _read(connector: Connector, method: str, *args: Any) -> Any:
    """A source figure; None if the connector can't provide it; the exception if reading it
    failed (recorded as an `_unavailable` issue)."""
    read = getattr(connector, method, None)
    if read is None:
        return None
    try:
        return read(*args)
    except Exception as exc:  # noqa: BLE001 - see the docstring
        return exc


def source_controls(
    connector: Connector,
    entity: SourceEntity,
    row: Entity,
    as_of: date,
    rule: DateRule = EVERY_DAY,
    progress: Progress | None = None,
) -> SourceControls:
    """The source's own figures for one entity (each read separately: one that fails or
    isn't supported doesn't stop the others). Year ends move to the source's next reliable
    date for a period end (Educational mode: a 30 June year end is checked on 2 July, never
    on the 1st). The source's own statements are read for the as-of date and each year end
    (ADR-040)."""
    books_from = entity.books_from or row.books_from
    bills = _read(connector, "bill_outstanding", entity)
    outstanding, opening = (
        (bills, bills) if bills is None or isinstance(bills, Exception) else bills
    )
    year_ends = {}
    if hasattr(connector, "closing_balances"):
        for year_end in financial_year_ends(row.books_from, row.fy_start_month, as_of):
            used = rule.period_end(year_end)
            if used > as_of:
                continue
            if used != year_end and progress:
                progress(f"year end {year_end} checked as of {used} ({rule.describe()})")
            year_ends[used] = _read(connector, "closing_balances", entity, used)
    statements = {}
    if hasattr(connector, "source_statements"):
        for on in {*year_ends, as_of}:
            statements[on] = _read(connector, "source_statements", entity, on)
    return SourceControls(
        voucher_counts=_read(connector, "voucher_counts", entity, books_from, as_of)
        if books_from
        else None,
        stock_quantities=_read(connector, "stock_quantities", entity, as_of),
        bill_outstanding=outstanding,
        opening_bills=opening,
        year_ends=year_ends,
        statements=statements,
    )


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
    def latest(self) -> list[ValidationReport]:
        """The last report per entity (an entity is validated again after deletions)."""
        return list({r.entity_id: r for r in self.reports}.values())

    @property
    def validation_status(self) -> str:
        if self.validation_error:
            return "failed"
        if not self.reports:
            return "not run"
        return "failed" if any(r.status == "failed" for r in self.latest) else "passed"


def entity_validator(
    session: Session,
    connection: Connection,
    connector: Connector,
    collect: AfterRun,
    progress: Progress | None = None,
    only_if_changed: bool = False,
    thorough: bool = False,
) -> Callable[[SyncResult, SourceEntity, bool], None]:
    """An `after_entity` hook for runs: validates each entity as soon as it is synced, so a
    later entity's failure can't hold it up (ADR-022). Never raises: a validation that can't
    run is recorded in `collect` and alerted, never a failed sync."""

    def validate(result: SyncResult, entity: SourceEntity, changed: bool) -> None:
        if only_if_changed and not changed:
            return
        try:
            collect.reports += run_validation(
                session,
                connection,
                connector,
                sync_run_id=result.sync_run_id,
                entity_keys=[entity.key],
                progress=progress,
                thorough=thorough,
            )
        except Exception as exc:  # noqa: BLE001 - see the docstring
            session.rollback()
            error = short_error(exc, redact=True)
            collect.validation_error = error
            raise_alert(
                session,
                "validation_failed",
                connection.id,
                f"Validation after {result.run_type} run {result.sync_run_id} couldn't run: "
                f"{error}",
                sync_run_id=result.sync_run_id,
            )
            logger.error("Validation in sync run %s couldn't run: %s", result.sync_run_id, error)

    return validate


def alert_for_run(session: Session, connection: Connection, result: SyncResult) -> bool:
    """Raises or resolves the run's own alert. True if the run succeeded."""
    kind = "deletion_check_failed" if result.run_type == DELETION_CHECK else "sync_failed"
    if (result.error or "").startswith(ExpectedEntityNotLoadedError.__name__):
        return False  # stopped before comparing anything: no alert (LB-SYNC-011)
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
