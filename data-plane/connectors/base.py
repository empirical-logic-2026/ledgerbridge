"""Standard connector interface (architecture.md Section 4.4, CON-001).

Nothing in this module is specific to a source. Each source lives in its own package
under `connectors/` and implements `Connector`.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
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


@dataclass(frozen=True)
class Chunk:
    """One piece of a fetch: an object type, optionally limited to a date range.

    Large sources are fetched chunk by chunk (masters per type, transactions per month,
    smaller ranges when a month is too slow), so each chunk can be stored, committed and
    checkpointed on its own (architecture ADR-022).
    """

    object_type: str
    period: Period | None = None

    @property
    def key(self) -> str:
        if self.period is None:
            return self.object_type
        return f"{self.object_type}:{self.period.start.isoformat()}..{self.period.end.isoformat()}"

    @property
    def label(self) -> str:
        """For progress output: the object type and dates only, never names."""
        if self.period is None:
            return self.object_type
        return f"{self.object_type} {self.period.start.isoformat()}..{self.period.end.isoformat()}"


class SourceTimeoutError(RuntimeError):
    """The source didn't answer one request in time (it may just be too large)."""


class SourceUnresponsiveError(RuntimeError):
    """The source doesn't answer even a minimal request: stop and resume later."""


@dataclass
class ConnectionStatus:
    ok: bool
    detail: str = ""
    info: dict[str, str] = field(default_factory=dict)


Markers = Mapping[str, str]  # object_type -> last change marker seen (e.g. Tally AlterID)


@dataclass(frozen=True)
class SourceBalances:
    """The source's own closing balances as of a date, for validation (VAL-002).

    Amounts use the canonical sign (debit positive). `profit_carriers` are ledgers whose
    source balance includes the period's computed profit (e.g. Tally's Profit & Loss A/c);
    the stock values (canonical sign, None if the source keeps no stock) are the ones the
    source uses when it computes that profit.
    """

    as_of: date
    ledgers: Mapping[str, Decimal]  # ledger source_key -> closing balance
    profit_carriers: frozenset[str] = frozenset()
    opening_stock: Decimal | None = None
    closing_stock: Decimal | None = None


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

    # --- optional: chunked fetching for large sources (ADR-022) ------------------------
    # A connector offering these lets the sync fetch, store and checkpoint chunk by chunk.

    def fetch_plan(
        self, entity: SourceEntity, markers: Markers | None, period: Period | None
    ) -> list[Chunk]:
        """The chunks of one entity's fetch, in transform order."""
        ...

    def fetch_chunk(
        self, entity: SourceEntity, chunk: Chunk, markers: Markers | None
    ) -> list[SourceRecord]:
        """One chunk's records. Raises SourceTimeoutError if the source is too slow."""
        ...

    def chunk_keys(self, entity: SourceEntity, chunk: Chunk) -> set[str]:
        """Keys only of a chunk (cheap): proves a split chunk was fetched completely."""
        ...

    def ping(self) -> None:
        """A minimal request with a short timeout; raises if the source doesn't answer."""
        ...

    def closing_balances(self, entity: SourceEntity, as_of: date) -> SourceBalances:
        """The source's closing balance of every ledger as of `as_of` (inclusive), from the
        entity's books-from date. Optional: validation skips closing checks without it."""
        ...
