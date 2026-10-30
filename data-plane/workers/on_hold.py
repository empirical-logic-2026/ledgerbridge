"""`./dev.ps1 on-hold`: put an entity on hold, take it off, or list them (SYN-007).

An entity on hold is skipped by sync, validation and statements unless it is named
explicitly (workers/entities.py), listed separately in the health report and left out of
its overall verdict (workers/report.py), and hidden from dashboards. Its stored data is
kept. Every change is written to the audit log (AUD-001). Output: entity labels only.
"""

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Connection
from core.models import accounting as A  # noqa: N812
from core.models.base import utcnow
from core.models.system import AuditLog
from workers.entities import Labels

Print = Callable[[str], None]


def set_on_hold(session: Session, entity_id: int, on_hold: bool, out: Print = print) -> int:
    """Puts the entity on hold (or takes it off) and audits the change; 2 for an unknown
    entity, 0 otherwise (also when nothing changed)."""
    entity = session.get(A.Entity, entity_id)
    if entity is None:
        out(f"No entity {entity_id}.")
        return 2
    label = _label(session, entity_id)
    if entity.is_on_hold == on_hold:
        out(f"{label}: already {_state(on_hold)}; nothing changed")
        return 0
    entity.is_on_hold = on_hold
    session.add(
        AuditLog(
            occurred_at=utcnow(),
            action="entity_on_hold_set" if on_hold else "entity_on_hold_cleared",
            object_type="entity",
            object_id=str(entity_id),
            entity_id=entity_id,
            details={"via": "dev.ps1 on-hold"},
        )
    )
    session.commit()
    out(f"{label}: {_state(on_hold)}")
    return 0


def list_entities(session: Session, out: Print = print) -> int:
    """Every entity with its state, those on hold first."""
    rows = session.execute(select(A.Entity.id, A.Entity.is_on_hold).order_by(A.Entity.id)).all()
    if not rows:
        out("No entities yet.")
        return 0
    for entity_id, on_hold in sorted(rows, key=lambda r: (not r[1], r[0])):
        out(f"{_label(session, entity_id)}: {_state(on_hold)}")
    return 0


def _state(on_hold: bool) -> str:
    return "on hold" if on_hold else "not on hold"


def _label(session: Session, entity_id: int) -> str:
    """`entity <id> (company <n>)` on the connection it came from, else `entity <id>`."""
    connection = session.scalar(
        select(Connection)
        .join(A.EntitySource, A.EntitySource.connection_id == Connection.id)
        .where(A.EntitySource.entity_id == entity_id)
        .order_by(A.EntitySource.id)
        .limit(1)
    )
    if connection is None:
        return f"entity {entity_id}"
    return Labels(session, connection).for_entity(entity_id)
