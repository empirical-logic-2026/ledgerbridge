"""Standard connector interface (architecture.md Section 4.4, CON-001).

Nothing in this module is specific to a source. Each source lives in its own package
under `connectors/` and implements `Connector`.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Protocol

from core.canonical import CanonicalRecord

PayloadFormat = Literal["xml", "json", "csv", "txt"]


@dataclass(frozen=True)
class SourceEntity:
    """A company/organization available in a source."""

    key: str  # stable identifier in the source (e.g. Tally company GUID)
    name: str
    books_from: date | None = None
    books_to: date | None = None


@dataclass(frozen=True)
class SourceRecord:
    """One source object, exactly as received, ready for ledgerbridge_source.raw_records."""

    source_entity_key: str
    object_type: str
    source_key: str
    source_alter_id: int | None
    payload_format: PayloadFormat
    payload: str


@dataclass(frozen=True)
class Period:
    start: date
    end: date


@dataclass
class ConnectionStatus:
    ok: bool
    detail: str = ""
    info: dict[str, str] = field(default_factory=dict)


Markers = Mapping[str, str]  # object_type -> last change marker seen (e.g. Tally AlterID)


class Connector(Protocol):
    source_code: str
    # Object types in the order they must be transformed (each may refer to earlier ones).
    object_types: tuple[str, ...]

    def test_connection(self) -> ConnectionStatus: ...

    def list_entities(self) -> list[SourceEntity]: ...

    def fetch_masters(
        self, entity: SourceEntity, markers: Markers | None = None
    ) -> Iterator[SourceRecord]:
        """Masters changed after the markers; everything when there is no marker."""
        ...

    def fetch_transactions(
        self,
        entity: SourceEntity,
        markers: Markers | None = None,
        period: Period | None = None,
    ) -> Iterator[SourceRecord]:
        """Transactions changed after the markers, or all in `period` / the whole books."""
        ...

    def list_keys(self, entity: SourceEntity) -> dict[str, set[str]]:
        """Every source key that currently exists, per object type (to detect deletions)."""
        ...

    def to_canonical(self, record: SourceRecord) -> list[CanonicalRecord]:
        """Map one raw record to canonical records (core/canonical.py)."""
        ...
