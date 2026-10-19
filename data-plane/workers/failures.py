"""Why raw records failed to transform, and what was kept aside: grouped counts that are
safe to share (pilot runbook). Source-independent.

Stored errors already hold the error type and a short message naming fields and columns,
never values (core/errors.py, core/fit.py). For display they are grouped further: quoted
text is removed, and sizes in parentheses ("values up to 300 characters") are taken out of
the group's message and shown as the largest size seen.

Where it fits: `summary` (workers/cli.py) and the health report (workers/report.py) print
these groups.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.errors import redact_quoted
from core.models.source import RawRecord

_SIZE = re.compile(r"\s*\(([^()]*\d[^()]*)\)")
_NUMBER = re.compile(r"\d[\d,]*")
MESSAGE_LENGTH = 160


@dataclass
class Group:
    object_type: str
    message: str  # error type and a short message: no values
    count: int
    largest: str | None = None  # e.g. "values up to 300 characters"


def normalise(message: str) -> tuple[str, list[str]]:
    """(message without quoted values or sizes, the sizes taken out)."""
    text = redact_quoted(message or "")
    sizes = _SIZE.findall(text)
    return _SIZE.sub("", text).strip()[:MESSAGE_LENGTH], sizes


def _largest(sizes: Iterable[str]) -> str | None:
    best, best_number = None, -1
    for size in sizes:
        numbers = [int(n.replace(",", "")) for n in _NUMBER.findall(size)]
        if numbers and max(numbers) > best_number:
            best, best_number = size, max(numbers)
    return best


def _group(rows: Iterable[tuple[str, str | None, int]]) -> list[Group]:
    groups: dict[tuple[str, str], Group] = {}
    sizes: dict[tuple[str, str], list[str]] = {}
    for object_type, message, count in rows:
        text, found = normalise(message or "unknown error")
        key = (object_type, text)
        if key not in groups:
            groups[key] = Group(object_type, text, 0)
            sizes[key] = []
        groups[key].count += count
        sizes[key] += found
    for key, group in groups.items():
        group.largest = _largest(sizes[key])
    return sorted(groups.values(), key=lambda g: (g.object_type, -g.count, g.message))


def failure_breakdown(
    session: Session, connection_id: int, entity_keys: list[str] | None = None
) -> list[Group]:
    """Failed raw records per object type and kind of error."""
    query = (
        select(RawRecord.object_type, RawRecord.process_error, func.count())
        .where(RawRecord.connection_id == connection_id, RawRecord.process_status == "failed")
        .group_by(RawRecord.object_type, RawRecord.process_error)
    )
    if entity_keys is not None:
        query = query.where(RawRecord.source_entity_key.in_(entity_keys))
    return _group(session.execute(query).all())  # type: ignore[arg-type]


def warning_breakdown(
    session: Session, connection_id: int, entity_keys: list[str] | None = None
) -> list[Group]:
    """Processed records that had values kept aside, per object type and kind."""
    query = (
        select(RawRecord.object_type, RawRecord.process_warning, func.count())
        .where(
            RawRecord.connection_id == connection_id,
            RawRecord.process_status == "processed",
            RawRecord.process_warning.is_not(None),
        )
        .group_by(RawRecord.object_type, RawRecord.process_warning)
    )
    if entity_keys is not None:
        query = query.where(RawRecord.source_entity_key.in_(entity_keys))
    rows = []
    for object_type, warnings, count in session.execute(query):
        for warning in (warnings or "").split("; "):
            if warning:
                rows.append((object_type, warning, count))
    return _group(rows)


def format_group(group: Group) -> str:
    largest = f" ({group.largest})" if group.largest else ""
    return f"{group.object_type} x{group.count:,}: {group.message}{largest}"
