"""Validation results and alerts (VAL-001 to VAL-003, SYN-006).

Read-only. Until M5 these endpoints have no authentication, which is acceptable only while
the API binds to 127.0.0.1 (ADR-019, tests/test_api_binding.py); M5 protects them with the
`validation.view` permission, and adds acknowledging alerts (a write).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import get_session
from core.models.accounting import Entity
from core.models.system import Alert, ValidationIssue, ValidationRun

router = APIRouter(prefix="/api", tags=["validation"])
DbSession = Annotated[Session, Depends(get_session)]


class ValidationRunOut(BaseModel):
    id: int
    entity_id: int
    sync_run_id: int | None
    as_of: date
    started_at: datetime
    status: str
    checks_passed: int
    checks_failed: int


class ValidationIssueOut(BaseModel):
    id: int
    check_code: str
    severity: str
    object_type: str | None
    object_id: str | None
    expected_value: Decimal | None
    actual_value: Decimal | None
    message: str
    resolved_at: datetime | None


class ValidationRunDetail(ValidationRunOut):
    issues: list[ValidationIssueOut]


class EntityValidationStatus(BaseModel):
    entity_id: int
    entity_code: str
    entity_name: str
    # Shown first on purpose: a difference in opening balances is a warning, not an error,
    # but it must be fixed in the source books (schema.md 5.2).
    opening_difference: Decimal | None
    last_run: ValidationRunOut | None
    open_errors: int
    open_warnings: int
    open_alerts: int


class AlertOut(BaseModel):
    id: int
    kind: str
    severity: str
    connection_id: int
    entity_id: int | None
    sync_run_id: int | None
    validation_run_id: int | None
    message: str
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    acknowledged_at: datetime | None


def _run_out(run: ValidationRun) -> ValidationRunOut:
    return ValidationRunOut.model_validate(run, from_attributes=True)


@router.get("/validation/status", response_model=list[EntityValidationStatus])
def validation_status(session: DbSession) -> list[EntityValidationStatus]:
    """The latest validation of every entity, with its open issues and alerts."""
    statuses = []
    for entity in session.scalars(select(Entity).order_by(Entity.name)):
        run = session.scalar(
            select(ValidationRun)
            .where(ValidationRun.entity_id == entity.id)
            .order_by(ValidationRun.id.desc())
            .limit(1)
        )
        issues = (
            session.scalars(
                select(ValidationIssue).where(ValidationIssue.validation_run_id == run.id)
            ).all()
            if run
            else []
        )
        opening = next((i for i in issues if i.check_code == "opening_difference"), None)
        statuses.append(
            EntityValidationStatus(
                entity_id=entity.id,
                entity_code=entity.code,
                entity_name=entity.name,
                opening_difference=opening.actual_value if opening else None,
                last_run=_run_out(run) if run else None,
                open_errors=sum(1 for i in issues if i.severity == "error"),
                open_warnings=sum(1 for i in issues if i.severity == "warning"),
                open_alerts=session.scalar(
                    select(func.count())
                    .select_from(Alert)
                    .where(Alert.entity_id == entity.id, Alert.resolved_at.is_(None))
                )
                or 0,
            )
        )
    return statuses


@router.get("/validation/runs", response_model=list[ValidationRunOut])
def validation_runs(
    session: DbSession,
    entity_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> list[ValidationRunOut]:
    query = select(ValidationRun).order_by(ValidationRun.id.desc()).limit(limit)
    if entity_id is not None:
        query = query.where(ValidationRun.entity_id == entity_id)
    return [_run_out(run) for run in session.scalars(query)]


@router.get("/validation/runs/{run_id}", response_model=ValidationRunDetail)
def validation_run(run_id: int, session: DbSession) -> ValidationRunDetail:
    run = session.get(ValidationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Validation run not found")
    issues = session.scalars(
        select(ValidationIssue)
        .where(ValidationIssue.validation_run_id == run.id)
        .order_by(ValidationIssue.id)
    )
    return ValidationRunDetail(
        **_run_out(run).model_dump(),
        issues=[ValidationIssueOut.model_validate(i, from_attributes=True) for i in issues],
    )


@router.get("/alerts", response_model=list[AlertOut])
def alerts(
    session: DbSession,
    open_only: bool = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AlertOut]:
    query = select(Alert).order_by(Alert.id.desc()).limit(limit)
    if open_only:
        query = query.where(Alert.resolved_at.is_(None))
    return [AlertOut.model_validate(a, from_attributes=True) for a in session.scalars(query)]
