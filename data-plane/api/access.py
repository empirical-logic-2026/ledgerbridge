"""Who may see what: one dependency for every `/api/v1` endpoint (ADR-049).

Until login (M5) there are no users: `current_access` allows every company that isn't on
hold (SYN-007). M5 replaces it here, in one place, with the logged-in user's companies and
permissions (ACC-002); the endpoints already filter every query through `Access`, so nothing
else changes. Companies outside the access are answered as not found, never as forbidden,
so their existence isn't revealed.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_report_session
from core.models import accounting as A  # noqa: N812


@dataclass(frozen=True)
class Access:
    """The companies (entity ids) the caller may see."""

    entity_ids: frozenset[int]

    def entities(self, requested: Iterable[int] | None = None) -> list[int]:
        """The requested companies, or all the caller may see; 404 for any other."""
        if requested is None:
            return sorted(self.entity_ids)
        wanted = sorted(set(requested))
        if not wanted:
            return sorted(self.entity_ids)
        if any(entity_id not in self.entity_ids for entity_id in wanted):
            raise HTTPException(status_code=404, detail="Company not found.")
        return wanted


def current_access(session: Annotated[Session, Depends(get_report_session)]) -> Access:
    """Every company not on hold (no login yet: ADR-049)."""
    ids = session.scalars(select(A.Entity.id).where(A.Entity.is_on_hold.is_(False)))
    return Access(frozenset(ids))


CurrentAccess = Annotated[Access, Depends(current_access)]
