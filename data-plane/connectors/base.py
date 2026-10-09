"""Standard connector interface (architecture.md Section 4.4, CON-001).

Nothing in this module is specific to a source. Each source lives in its own package
under `connectors/` and implements `Connector`.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Protocol

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


class Connector(Protocol):
    source_code: str

    def test_connection(self) -> ConnectionStatus: ...

    def list_entities(self) -> list[SourceEntity]: ...

    def fetch_masters(
        self, entity: SourceEntity, since_marker: str | None = None
    ) -> Iterator[SourceRecord]: ...

    def fetch_transactions(
        self,
        entity: SourceEntity,
        since_marker: str | None = None,
        period: Period | None = None,
    ) -> Iterator[SourceRecord]: ...

    def to_canonical(self, record: SourceRecord) -> object:
        """Map a raw record to canonical rows. Implemented from M3."""
        ...
