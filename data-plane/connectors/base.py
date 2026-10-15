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
    # The source's own difference in opening balances at the books' beginning (canonical
    # sign; zero when its trial balance from the books' beginning balances). None: unknown.
    opening_difference: Decimal | None = None
    # Each ledger's opening at the books' beginning in the source (canonical sign).
    ledger_openings: Mapping[str, Decimal] = field(default_factory=dict)
    # The openings of the source's stock ledgers (Tally: under Stock-in-Hand), totalled.
    stock_ledger_openings: Decimal | None = None


@dataclass(frozen=True)
class SourceControls:
    """The source's own figures that prove the books complete, beyond closing balances
    (VAL-005 to VAL-008). Each is None when the source can't report it, or the exception
    that prevented reading it. Amounts use the canonical sign (debit positive).

    - `voucher_counts`: (first day of the month, voucher type name) -> number of vouchers
      dated in that month, up to the as-of date (cancelled and optional ones included);
    - `stock_quantities`: stock item source_key -> closing quantity as of the date;
    - `bill_outstanding`: party ledger name -> total of its outstanding bills, as the source
      reports them now; `opening_bills`: party ledger name -> total of its opening bills;
    - `year_ends`: each financial year end before the as-of date -> closing balances then.
    """

    voucher_counts: Mapping[tuple[date, str], int] | Exception | None = None
    stock_quantities: Mapping[str, Decimal] | Exception | None = None
    bill_outstanding: Mapping[str, Decimal] | Exception | None = None
    opening_bills: Mapping[str, Decimal] | Exception | None = None
    year_ends: Mapping[date, "SourceBalances | Exception"] = field(default_factory=dict)


class Connector(Protocol):
    source_code: str
    # Object types in the order they must be transformed (each may refer to earlier ones). The
    # first is the entity's own record (e.g. a Tally company), which creates the entity.
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
        self,
        entity: SourceEntity,
        chunk: Chunk,
        markers: Markers | None,
        timeout: float | None = None,
    ) -> list[SourceRecord]:
        """One chunk's records (only those dated within its period). Raises
        SourceTimeoutError if the source is too slow; `timeout` overrides the connection's."""
        ...

    def chunk_keys(
        self, entity: SourceEntity, chunk: Chunk, timeout: float | None = None
    ) -> set[str]:
        """Keys only of a chunk (cheap): proves a split chunk was fetched completely."""
        ...

    def ping(self) -> None:
        """A minimal request with a short timeout; raises if the source doesn't answer."""
        ...

    def closing_balances(self, entity: SourceEntity, as_of: date) -> SourceBalances:
        """The source's closing balance of every ledger as of `as_of` (inclusive), from the
        entity's books-from date. Optional: validation skips closing checks without it."""
        ...

    # --- optional: figures that prove the books complete (VAL-005 to VAL-008) -----------

    def voucher_counts(
        self, entity: SourceEntity, start: date, end: date
    ) -> dict[tuple[date, str], int]:
        """(month start, voucher type name) -> vouchers dated start..end (inclusive)."""
        ...

    def stock_quantities(self, entity: SourceEntity, as_of: date) -> dict[str, Decimal]:
        """Stock item source_key -> closing quantity as of `as_of`."""
        ...

    def bill_outstanding(
        self, entity: SourceEntity
    ) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
        """(outstanding bills now, opening bills), each party ledger name -> total."""
        ...
