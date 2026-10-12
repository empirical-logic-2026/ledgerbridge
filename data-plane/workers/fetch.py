"""Fetching one entity chunk by chunk, resiliently (ADR-022). Source-independent.

The connector divides an entity into chunks (`fetch_plan`: masters per type, transactions
per month). For each chunk:

1. Fetch it and **store and commit it at once**, so a failure later loses at most the chunk
   in hand, never the chunks before it.
2. **Checkpoint** it (full syncs): an interrupted full sync skips completed chunks when run
   again, unless asked to start over.
3. **On a timeout**, check the source with a minimal request first (waiting longer between
   attempts). If it doesn't answer at all, stop: the run can resume later. If it answers,
   the chunk was too large: **split** it (month, half-month, week, day) and fetch the pieces.
   A split chunk is then **verified** against a keys-only listing of the whole chunk, so a
   piece the source silently left empty can't go unnoticed. The month is **remembered** as
   slow, and later runs request it in pieces straight away.

Progress lines carry object types, dates and counts only, never names.
"""

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from connectors.base import (
    Chunk,
    Connector,
    Markers,
    Period,
    SourceEntity,
    SourceTimeoutError,
    SourceUnresponsiveError,
)
from core.errors import short_error
from core.models.base import utcnow
from core.models.system import SyncCheckpoint, SyncSlowPeriod
from core.raw_store import RawStore

# Waits before re-checking a source that didn't answer the minimal request (seconds).
BACKOFF_SEC: tuple[float, ...] = (10.0, 30.0, 90.0)
# A minimal request answered slower than this means "slow but responding".
SLOW_ANSWER_SEC = 10.0
# Checkpoints older than this are ignored: their data may have changed meanwhile.
CHECKPOINT_MAX_AGE = timedelta(days=7)


class IncompleteChunkError(RuntimeError):
    """A split chunk's pieces didn't return everything the source lists for the chunk."""


def split_period(period: Period) -> list[Period] | None:
    """Month -> two halves -> weeks -> days; None for a single day."""
    days = (period.end - period.start).days + 1
    if days <= 1:
        return None
    if days > 16:
        size = (days + 1) // 2
    elif days > 7:
        size = 7
    else:
        size = 1
    return pieces(period, size)


def pieces(period: Period, size: int) -> list[Period]:
    parts, start = [], period.start
    while start <= period.end:
        end = min(period.end, start + timedelta(days=size - 1))
        parts.append(Period(start, end))
        start = end + timedelta(days=1)
    return parts


@dataclass
class FetchStats:
    """What one entity's fetch did, in this run."""

    fetched: Counter[str] = field(default_factory=Counter)
    stored: int = 0
    unchanged: int = 0
    chunks: int = 0  # in the plan
    chunks_done: int = 0  # fetched in this run
    chunks_skipped: int = 0  # done by an earlier attempt (checkpoints)
    splits: int = 0
    unverified: list[str] = field(default_factory=list)  # split chunks that couldn't be checked


class ChunkFetcher:
    def __init__(
        self,
        session: Session,
        connection_id: int,
        connector: Connector,
        sync_run_id: int,
        say: Callable[[str], None],
        label: str,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        backoff: tuple[float, ...] = BACKOFF_SEC,
    ) -> None:
        self.session = session
        self.connection_id = connection_id
        self.connector = connector
        self.sync_run_id = sync_run_id
        self.say = say
        self.label = label
        self.sleep = sleep
        self.clock = clock
        self.backoff = backoff
        self.store = RawStore(session)
        self.stats = FetchStats()

    # --- one entity -------------------------------------------------------------------

    def fetch_entity(
        self,
        entity: SourceEntity,
        markers: Markers,
        period: Period | None,
        resumable: bool,
        restart: bool = False,
        reprocess_unchanged: bool = False,
    ) -> FetchStats:
        self.entity = entity
        self.markers = markers
        self.reprocess = reprocess_unchanged
        plan = self.connector.fetch_plan(entity, markers, period)
        self.stats.chunks = len(plan)
        done = self._checkpoints(entity, restart) if resumable else set()
        if done:
            self.say(
                f"{self.label}: resuming: {len(done)} of {len(plan)} chunks were completed by "
                "an earlier attempt (use restart to fetch everything again)"
            )
        slow = self._slow_months(entity)
        for number, chunk in enumerate(plan, start=1):
            position = f"chunk {number} of {len(plan)}"
            # The entity's own record is always fetched (cheap; it carries its settings).
            if chunk.key in done and number > 1:
                self.stats.chunks_skipped += 1
                continue
            before = sum(self.stats.fetched.values())
            month = _month(chunk)
            if month is not None and month in slow and not markers:
                parts = pieces(chunk.period, slow[month])  # type: ignore[arg-type]
                self.say(
                    f"{self.label}: {chunk.label} was slow before: fetching it in "
                    f"{len(parts)} parts ({position})"
                )
                keys: set[str] = set()
                for part in parts:
                    keys |= self._fetch(Chunk(chunk.object_type, part), position)
                self._verify(chunk, keys)
            else:
                self._fetch(chunk, position)
            self.stats.chunks_done += 1
            if resumable and chunk.key not in done:
                self._checkpoint(entity, chunk, sum(self.stats.fetched.values()) - before)
        return self.stats

    def clear_checkpoints(self, entity: SourceEntity) -> None:
        self.session.execute(
            delete(SyncCheckpoint).where(
                SyncCheckpoint.connection_id == self.connection_id,
                SyncCheckpoint.source_entity_key == entity.key,
            )
        )
        self.session.commit()

    # --- one chunk --------------------------------------------------------------------

    def _fetch(self, chunk: Chunk, position: str) -> set[str]:
        """Fetches, stores and commits one chunk (splitting it if needed); returns its keys."""
        try:
            records = self.connector.fetch_chunk(self.entity, chunk, self.markers)
        except SourceTimeoutError as exc:
            self.say(f"{self.label}: {chunk.label} timed out ({short_error(exc, redact=True)})")
            self.check_source()
            parts = split_period(chunk.period) if chunk.period is not None else None
            if not parts:
                self.say(f"{self.label}: {chunk.label} can't be split further; trying it once more")
                records = self.connector.fetch_chunk(self.entity, chunk, self.markers)
            else:
                self.stats.splits += 1
                self.say(
                    f"{self.label}: the request was too large: fetching {chunk.label} "
                    f"in {len(parts)} parts"
                )
                keys: set[str] = set()
                for part in parts:
                    keys |= self._fetch(Chunk(chunk.object_type, part), position)
                self._remember_slow(chunk, parts)
                self._verify(chunk, keys)
                return keys
        result = self.store.add(
            records,
            self.connection_id,
            self.sync_run_id,
            reprocess_unchanged=self.reprocess,
        )  # commits
        for record in records:
            self.stats.fetched[record.object_type] += 1
        self.stats.stored += result.stored
        self.stats.unchanged += result.skipped
        self.say(
            f"{self.label}: {chunk.label}: {len(records):,} received, {result.stored:,} stored, "
            f"{result.skipped:,} unchanged ({position})"
        )
        return {record.source_key for record in records}

    def _verify(self, chunk: Chunk, fetched: set[str]) -> None:
        """A chunk fetched in parts must contain every key the source lists for it."""
        if chunk.period is None or self.markers or not hasattr(self.connector, "chunk_keys"):
            return
        try:
            listed = self.connector.chunk_keys(self.entity, chunk)
        except SourceTimeoutError:
            self.stats.unverified.append(chunk.label)
            self.say(f"{self.label}: WARNING: couldn't verify {chunk.label} (listing too slow)")
            return
        missing = listed - fetched
        if missing:
            raise IncompleteChunkError(
                f"{chunk.label}: the source lists {len(missing)} objects that its parts didn't "
                "return (it may not support requests for parts of a month)"
            )
        self.say(f"{self.label}: {chunk.label}: verified complete ({len(listed):,} objects)")

    def check_source(self) -> None:
        """After a timeout: does the source answer a minimal request? Waits and re-checks
        with growing pauses; raises SourceUnresponsiveError if it never answers."""
        if not hasattr(self.connector, "ping"):
            return
        attempts = (0.0, *self.backoff)
        for attempt, wait in enumerate(attempts, start=1):
            if wait:
                self.say(f"{self.label}: waiting {wait:g} s before checking the source again")
                self.sleep(wait)
            started = self.clock()
            try:
                self.connector.ping()
            except Exception as exc:  # noqa: BLE001 - any failure means "no answer"
                self.say(
                    f"{self.label}: source check {attempt} of {len(attempts)}: no answer "
                    f"({short_error(exc, redact=True)})"
                )
                continue
            elapsed = self.clock() - started
            if elapsed > SLOW_ANSWER_SEC:
                self.say(
                    f"{self.label}: the source answered the check in {elapsed:.1f} s: "
                    "it is slow, but responding"
                )
            else:
                self.say(
                    f"{self.label}: the source answered the check in {elapsed:.1f} s: "
                    "responsive, so the request was too large"
                )
            return
        self.say(
            f"{self.label}: the source appears UNRESPONSIVE: stopping. Everything fetched so far "
            "is stored; run the sync again to continue from there."
        )
        raise SourceUnresponsiveError("the source doesn't answer a minimal request")

    # --- checkpoints and slow months --------------------------------------------------

    def _checkpoints(self, entity: SourceEntity, restart: bool) -> set[str]:
        expired = utcnow() - CHECKPOINT_MAX_AGE
        query = delete(SyncCheckpoint).where(
            SyncCheckpoint.connection_id == self.connection_id,
            SyncCheckpoint.source_entity_key == entity.key,
        )
        if not restart:
            query = query.where(SyncCheckpoint.created_at < expired)
        self.session.execute(query)
        self.session.commit()
        return set(
            self.session.scalars(
                select(SyncCheckpoint.chunk_key).where(
                    SyncCheckpoint.connection_id == self.connection_id,
                    SyncCheckpoint.source_entity_key == entity.key,
                )
            )
        )

    def _checkpoint(self, entity: SourceEntity, chunk: Chunk, records: int) -> None:
        # A plain insert: checkpoints are deleted in bulk, so no ORM objects are kept for them.
        self.session.execute(
            insert(SyncCheckpoint).values(
                connection_id=self.connection_id,
                source_entity_key=entity.key,
                object_type=chunk.object_type,
                chunk_key=chunk.key,
                records=records,
                sync_run_id=self.sync_run_id,
            )
        )
        self.session.commit()

    def _slow_months(self, entity: SourceEntity) -> dict[date, int]:
        return dict(
            self.session.execute(
                select(SyncSlowPeriod.month, SyncSlowPeriod.piece_days).where(
                    SyncSlowPeriod.connection_id == self.connection_id,
                    SyncSlowPeriod.source_entity_key == entity.key,
                )
            ).all()
        )

    def _remember_slow(self, chunk: Chunk, parts: list[Period]) -> None:
        month = _month(chunk)
        if month is None:
            return
        size = (parts[0].end - parts[0].start).days + 1
        key = (self.connection_id, self.entity.key, chunk.object_type, month)
        row = self.session.get(SyncSlowPeriod, key)
        if row is None:
            self.session.add(
                SyncSlowPeriod(
                    connection_id=self.connection_id,
                    source_entity_key=self.entity.key,
                    object_type=chunk.object_type,
                    month=month,
                    piece_days=size,
                )
            )
        elif size < row.piece_days:
            row.piece_days = size
        self.session.commit()


def _month(chunk: Chunk) -> date | None:
    if chunk.period is None:
        return None
    return chunk.period.start.replace(day=1)
