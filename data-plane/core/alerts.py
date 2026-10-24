"""Alerts for sync and validation failures (SYN-006, ADR-019).

An alert is raised when something starts failing and resolved when it works again: one
open alert per connection and kind (per entity for validation). A failure that repeats
every few minutes updates the open alert instead of creating new ones. Every resolution
records its reason (`alerts.resolution`), e.g. the run that passed, or that the company
the alert was about is no longer on the connection.

The `ledgerbridge_system.alerts` row is the in-app channel. Further channels get the
raise and resolve events through `AlertChannel`: the log now, email later. Messages hold
counts and check codes only, never amounts or names.
"""

import logging
from collections.abc import Sequence
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.base import utcnow
from core.models.system import Alert

logger = logging.getLogger(__name__)


class AlertChannel(Protocol):
    def raised(self, alert: Alert) -> None: ...

    def resolved(self, alert: Alert) -> None: ...


class LogChannel:
    def raised(self, alert: Alert) -> None:
        logger.warning(
            "Alert %s raised: %s on connection %s%s: %s",
            alert.id,
            alert.kind,
            alert.connection_id,
            f", entity {alert.entity_id}" if alert.entity_id else "",
            alert.message,
        )

    def resolved(self, alert: Alert) -> None:
        logger.info(
            "Alert %s resolved: %s on connection %s (%s)",
            alert.id,
            alert.kind,
            alert.connection_id,
            alert.resolution,
        )


DEFAULT_CHANNELS: Sequence[AlertChannel] = (LogChannel(),)


def open_alert(
    session: Session, kind: str, connection_id: int, entity_id: int | None = None
) -> Alert | None:
    return session.scalar(
        select(Alert)
        .where(
            Alert.kind == kind,
            Alert.connection_id == connection_id,
            Alert.entity_id.is_(None) if entity_id is None else Alert.entity_id == entity_id,
            Alert.resolved_at.is_(None),
        )
        .order_by(Alert.id.desc())
        .limit(1)
    )


def raise_alert(
    session: Session,
    kind: str,
    connection_id: int,
    message: str,
    *,
    entity_id: int | None = None,
    sync_run_id: int | None = None,
    validation_run_id: int | None = None,
    severity: str = "error",
    channels: Sequence[AlertChannel] = DEFAULT_CHANNELS,
) -> Alert:
    """Opens an alert, or brings the open one up to date (no new notification)."""
    alert = open_alert(session, kind, connection_id, entity_id)
    if alert is not None:
        alert.message = message
        alert.sync_run_id = sync_run_id or alert.sync_run_id
        alert.validation_run_id = validation_run_id or alert.validation_run_id
        alert.updated_at = utcnow()
        session.commit()
        return alert
    alert = Alert(
        kind=kind,
        severity=severity,
        connection_id=connection_id,
        entity_id=entity_id,
        sync_run_id=sync_run_id,
        validation_run_id=validation_run_id,
        message=message,
    )
    session.add(alert)
    session.commit()
    for channel in channels:
        channel.raised(alert)
    return alert


def resolve_alert(
    session: Session,
    kind: str,
    connection_id: int,
    *,
    reason: str,
    entity_id: int | None = None,
    channels: Sequence[AlertChannel] = DEFAULT_CHANNELS,
) -> Alert | None:
    """Resolves the open alert of this kind, if any, recording why."""
    alert = open_alert(session, kind, connection_id, entity_id)
    if alert is None:
        return None
    _resolve(session, alert, reason, channels)
    return alert


def resolve_alerts_of_other_entities(
    session: Session,
    kind: str,
    connection_id: int,
    entity_ids: set[int],
    *,
    reason: str,
    channels: Sequence[AlertChannel] = DEFAULT_CHANNELS,
) -> list[Alert]:
    """Resolves open alerts of this kind about an entity not in `entity_ids` (one no longer
    on the connection: no run of it will ever resolve them)."""
    query = select(Alert).where(
        Alert.kind == kind,
        Alert.connection_id == connection_id,
        Alert.entity_id.is_not(None),
        Alert.resolved_at.is_(None),
    )
    if entity_ids:
        query = query.where(Alert.entity_id.not_in(entity_ids))
    found = list(session.scalars(query))
    for alert in found:
        _resolve(session, alert, reason, channels)
    return found


def _resolve(session: Session, alert: Alert, reason: str, channels: Sequence[AlertChannel]) -> None:
    alert.resolved_at = alert.updated_at = utcnow()
    alert.resolution = reason[:255]
    session.commit()
    for channel in channels:
        channel.resolved(alert)
