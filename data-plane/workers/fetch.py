"""Fetching one entity chunk by chunk, resiliently (ADR-022, ADR-023). Source-independent.

The connector divides an entity into chunks (`fetch_plan`: masters per type, transactions
per month). For each chunk:

1. Fetch it and **store and commit it at once**, so a failure later loses at most the chunk
   in hand, never the chunks before it.
2. **Checkpoint** it (full syncs), but only once it is known to be complete: an interrupted
   full sync skips completed chunks when run again.
3. **On a timeout**, check the source with a minimal request first (waiting longer between
   attempts); if it doesn't answer at all, stop: the run can resume later. If it answers:
   - and the source **supports requests for part of a month** (probed once per connection
     and stored), split the chunk (month, half-month, week, day), fetch the pieces, verify
     the whole month against its keys-only listing, and remember the month as slow;
   - otherwise **never split**: retry the whole month with longer timeouts (300, 600,
     1200 s by default), pausing first, and stop with a clear message if it still fails.
4. A month that comes back **empty while its months normally have many** records is
   confirmed against its listing before it counts as done.

Anything that can't be proven complete is recorded in `sync_unverified_ranges` and stops
the sync. A recorded range is fetched again on every run until it verifies, whatever its
checkpoint says. Progress lines carry object types, dates and counts only, never names.
"""

import statistics
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from connectors.base import (
    Chunk,
    Connector,
    Markers,
    Period,
    SourceEntity,
    SourceRecord,
    SourceTimeoutError,
    SourceUnresponsiveError,
)
from core.errors import short_error
from core.models.base import utcnow
from core.models.system import SyncCheckpoint, SyncSlowPeriod, SyncUnverifiedRange
from core.raw_store import RawStore

# Waits before re-checking a source that didn't answer the minimal request (seconds).
BACKOFF_SEC: tuple[float, ...] = (10.0, 30.0, 90.0)
# A minimal request answered slower than this means "slow but responding".
SLOW_ANSWER_SEC = 10.0
# Checkpoints older than this are ignored: their data may have changed meanwhile.
CHECKPOINT_MAX_AGE = timedelta(days=7)
# Retrying a chunk that can't be split: these timeouts (those above the connection's).
RETRY_TIMEOUTS_SEC: tuple[float, ...] = (300.0, 600.0, 1200.0)
# Pause before each such retry, to let the source recover.
RETRY_PAUSE_SEC = 60.0
# A month that comes back empty is checked when the entity's months typically have this many.
TYPICAL_MONTH_AT_LEAST = 20
# Part-month support, as stored on the connection (connections.config.part_month_requests).
SUPPORTED, UNSUPPORTED, AUTO = "supported", "unsupported", "auto"


class IncompleteChunkError(RuntimeError):
    """A chunk's records don't match what the source lists for it."""


class UnverifiedChunkError(RuntimeError):
    """A chunk couldn't be proven complete (e.g. its listing was too slow): not checkpointed."""


class ChunkTooSlowError(SourceTimeoutError):
    """A chunk that can't be split didn't arrive even with the longest timeout."""


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


def chunk_period(chunk_key: str) -> Period | None:
    """The period of a stored chunk key ('voucher:2024-03-01..2024-03-31'), if dated."""
    _, _, dates = chunk_key.partition(":")
    if ".." not in dates:
        return None
    start, end = dates.split("..")
    return Period(date.fromisoformat(start), date.fromisoformat(end))


@dataclass(frozen=True)
class FetchSettings:
    """A connection's fetch settings (connections.config; ADR-023)."""

    timeout_sec: float  # the connection's own, else TALLY_TIMEOUT_SEC
    pause_sec: float = 0.0  # between chunk requests, to ease the load on the source
    part_month: str = AUTO  # supported / unsupported / auto (probe once and store)
    retry_timeouts: tuple[float, ...] = RETRY_TIMEOUTS_SEC
    retry_pause_sec: float = RETRY_PAUSE_SEC

    def retry_ladder(self) -> list[float]:
        longer = [t for t in self.retry_timeouts if t > self.timeout_sec]
        return longer or [self.timeout_sec * 2]


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
    retries: int = 0  # whole-chunk retries with a longer timeout
    unverified: list[str] = field(default_factory=list)  # ranges recorded as unverified


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
        settings: FetchSettings | None = None,
        on_part_month: Callable[[str], None] | None = None,
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
        self.settings = settings or FetchSettings(timeout_sec=120.0)
        self.on_part_month = on_part_month
        self.store = RawStore(session)
        self.stats = FetchStats()
        self.plan: list[Chunk] = []
        self._requested = False  # for the pause between requests
        self._month_counts: list[int] = []

    # --- one entity -------------------------------------------------------------------

    def fetch_entity(
        self,
        entity: SourceEntity,
        markers: Markers,
        period: Period | None,
        resumable: bool,
        restart: bool = False,
        reprocess_unchanged: bool = False,
        refetch_from: date | None = None,
    ) -> FetchStats:
        self.entity = entity
        self.markers = markers
        self.reprocess = reprocess_unchanged
        self.plan = self.connector.fetch_plan(entity, markers, period)
        self.stats.chunks = len(self.plan)
        if resumable and refetch_from is not None:
            self.invalidate_from(entity, refetch_from)
        done = self._checkpoints(entity, restart) if resumable else {}
        reopened = self._reopen_unverified(entity, self.plan, done)
        if done:
            self.say(
                f"{self.label}: resuming: {len(done)} of {len(self.plan)} chunks were completed "
                "by an earlier attempt (use restart to fetch everything again)"
            )
        if reopened:
            self.say(
                f"{self.label}: {len(reopened)} chunks overlap ranges left unverified by an "
                "earlier attempt: fetching them again"
            )
        self._month_counts = [n for key, n in done.items() if chunk_period(key) and n > 0]
        slow = self._slow_months(entity)
        for number, chunk in enumerate(self.plan, start=1):
            position = f"chunk {number} of {len(self.plan)}"
            # The entity's own record is always fetched (cheap; it carries its settings).
            if chunk.key in done and number > 1:
                self.stats.chunks_skipped += 1
                continue
            month = _month(chunk)
            if month is not None and month in slow and not markers and self._parts_supported():
                parts = pieces(chunk.period, slow[month])  # type: ignore[arg-type]
                self.say(
                    f"{self.label}: {chunk.label} was slow before: fetching it in "
                    f"{len(parts)} parts ({position})"
                )
                keys: set[str] = set()
                for part in parts:
                    keys |= self._fetch(Chunk(chunk.object_type, part), position, top=False)
                self._verify(chunk, keys)
            else:
                keys = self._fetch(chunk, position)
            if chunk.period is not None and not markers:
                self._check_not_suspiciously_empty(chunk, keys)
                self._month_counts.append(len(keys))
            self._resolve_unverified(chunk)
            self.stats.chunks_done += 1
            if resumable and chunk.key not in done:
                self._checkpoint(entity, chunk, len(keys))
        return self.stats

    def clear_checkpoints(self, entity: SourceEntity) -> None:
        self.session.execute(
            delete(SyncCheckpoint).where(
                SyncCheckpoint.connection_id == self.connection_id,
                SyncCheckpoint.source_entity_key == entity.key,
            )
        )
        self.session.commit()

    def invalidate_from(self, entity: SourceEntity, day: date) -> int:
        """Forgets the checkpoints of dated chunks ending on or after `day`, so an
        interrupted full sync fetches them again (e.g. a damaged range)."""
        rows = self.session.execute(
            select(SyncCheckpoint.id, SyncCheckpoint.chunk_key).where(
                SyncCheckpoint.connection_id == self.connection_id,
                SyncCheckpoint.source_entity_key == entity.key,
            )
        ).all()
        ids = [i for i, key in rows if (p := chunk_period(key)) is not None and p.end >= day]
        if ids:
            self.session.execute(delete(SyncCheckpoint).where(SyncCheckpoint.id.in_(ids)))
            self.session.commit()
        self.say(f"{self.label}: from {day}: {len(ids)} completed chunks will be fetched again")
        return len(ids)

    # --- one chunk --------------------------------------------------------------------

    def _pace(self) -> None:
        """The connection's pause between requests (if any), to ease the load on the source."""
        if self._requested and self.settings.pause_sec:
            self.sleep(self.settings.pause_sec)
        self._requested = True

    def _fetch(self, chunk: Chunk, position: str, top: bool = True) -> set[str]:
        """Fetches, stores and commits one chunk; returns its keys. `top`: a plan chunk,
        verified as a whole when it had to be fetched in parts."""
        self._pace()
        try:
            records = self.connector.fetch_chunk(self.entity, chunk, self.markers)
        except SourceTimeoutError as exc:
            self.say(f"{self.label}: {chunk.label} timed out ({short_error(exc, redact=True)})")
            self.check_source()
            parts = split_period(chunk.period) if chunk.period is not None else None
            if parts and self._parts_supported():
                self.stats.splits += 1
                self.say(
                    f"{self.label}: the request was too large: fetching {chunk.label} "
                    f"in {len(parts)} parts"
                )
                keys: set[str] = set()
                for part in parts:
                    keys |= self._fetch(Chunk(chunk.object_type, part), position, top=False)
                self._remember_slow(chunk, parts)
                if top:
                    self._verify(chunk, keys)
                return keys
            records = self._retry_whole(chunk)
        result = self.store.add(
            records, self.connection_id, self.sync_run_id, reprocess_unchanged=self.reprocess
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

    def _retry_whole(self, chunk: Chunk) -> list[SourceRecord]:
        """A chunk that won't be split: retry it whole with longer timeouts, pausing first."""
        why = (
            "the source can't answer requests for part of a month"
            if chunk.period is not None and self.settings.part_month != SUPPORTED
            else "it can't be split further"
        )
        ladder = self.settings.retry_ladder()
        for timeout in ladder:
            self.stats.retries += 1
            pause = self.settings.retry_pause_sec
            self.say(
                f"{self.label}: {chunk.label} isn't split ({why}): waiting {pause:g} s, then "
                f"asking for it whole with a {timeout:g} s timeout"
            )
            self.sleep(pause)
            self.check_source()
            try:
                return self.connector.fetch_chunk(self.entity, chunk, self.markers, timeout=timeout)
            except SourceTimeoutError:
                self.say(f"{self.label}: {chunk.label}: still no answer within {timeout:g} s")
        raise ChunkTooSlowError(
            f"{chunk.label}: no answer within {ladder[-1]:g} s even as a whole ({why}). "
            "Everything before it is stored; run the sync again later, or give the connection "
            "a longer timeout (connect --timeout-sec)"
        )

    def _verify(self, chunk: Chunk, fetched: set[str]) -> None:
        """A chunk fetched in parts must contain every key the source lists for it. If that
        can't be shown, the range is recorded and the sync stops: never checkpointed."""
        if chunk.period is None or self.markers or not hasattr(self.connector, "chunk_keys"):
            return
        listed = self._listing(chunk, "it was fetched in parts")
        missing = listed - fetched
        if missing:
            reason = f"the source lists {len(missing)} objects its parts didn't return"
            self._record_unverified(chunk, reason)
            raise IncompleteChunkError(
                f"{chunk.label}: {reason} (it may not support requests for parts of a month)"
            )
        self.say(f"{self.label}: {chunk.label}: verified complete ({len(listed):,} objects)")

    def _check_not_suspiciously_empty(self, chunk: Chunk, fetched: set[str]) -> None:
        """A month that comes back empty while the entity's months typically have many
        records must be confirmed by the source's listing before it counts as done."""
        if fetched or not self._month_counts or not hasattr(self.connector, "chunk_keys"):
            return
        typical = statistics.median(self._month_counts)
        if typical < TYPICAL_MONTH_AT_LEAST:
            return
        self.say(
            f"{self.label}: {chunk.label} returned nothing, but months typically have about "
            f"{typical:,.0f} records: checking the source's listing"
        )
        listed = self._listing(chunk, "it came back empty")
        if listed:
            reason = f"empty, but the source lists {len(listed)} objects for it"
            self._record_unverified(chunk, reason)
            raise IncompleteChunkError(f"{chunk.label}: {reason}")
        self.say(f"{self.label}: {chunk.label}: confirmed empty by the source's listing")

    def _listing(self, chunk: Chunk, context: str) -> set[str]:
        self._pace()
        try:
            return self.connector.chunk_keys(self.entity, chunk)
        except SourceTimeoutError as exc:
            reason = f"{context}, but its listing didn't arrive in time"
            self._record_unverified(chunk, reason)
            raise UnverifiedChunkError(
                f"{chunk.label}: {reason} ({short_error(exc, redact=True)}). It isn't counted as "
                "complete and will be fetched again: run the sync again, if needed with a longer "
                "timeout (connect --timeout-sec)"
            ) from exc

    def check_source(self) -> None:
        """After a timeout: does the source answer a minimal request?

        Tally works on one request at a time and goes on with a request the client has given
        up on, so right after a timeout it may simply still be busy. The check therefore keeps
        trying, with growing pauses, for up to the connection's timeout (at least the default
        backoff) before declaring the source unresponsive (pilot 2026-10-13)."""
        if not hasattr(self.connector, "ping"):
            return
        budget = max(self.settings.timeout_sec, sum(self.backoff))
        waits = [*self.backoff]
        waited, attempt, wait = 0.0, 0, 0.0
        while True:
            attempt += 1
            if wait:
                self.say(
                    f"{self.label}: no answer yet; the source may still be busy with the request "
                    f"that timed out. Checking again in {wait:g} s "
                    f"({waited:g} of up to {budget:g} s waited)"
                )
                self.sleep(wait)
                waited += wait
            started = self.clock()
            try:
                self.connector.ping()
            except Exception as exc:  # noqa: BLE001 - any failure means "no answer"
                waited += self.clock() - started
                self.say(
                    f"{self.label}: source check {attempt}: no answer "
                    f"({short_error(exc, redact=True)})"
                )
                if waited >= budget:
                    break
                wait = min(waits.pop(0) if waits else self.backoff[-1], budget - waited)
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
                    + (f" (it became free after about {waited:g} s)" if waited else "")
                )
            return
        self.say(
            f"{self.label}: the source appears UNRESPONSIVE: no answer for {waited:g} s after the "
            "timeout, although that is as long as the request itself was allowed. Stopping. "
            "Everything fetched so far is stored; restart the source if needed, then run the "
            "sync again to continue from there."
        )
        raise SourceUnresponsiveError(f"the source hasn't answered for {waited:g} s")

    # --- part-month support -----------------------------------------------------------

    def _parts_supported(self) -> bool:
        """Whether requests for part of a month may be used; probed once per connection."""
        if self.settings.part_month == AUTO:
            result = self.probe_part_months()
            self.settings = replace(self.settings, part_month=result)
            if self.on_part_month is not None and result != AUTO:
                self.on_part_month(result)
        return self.settings.part_month == SUPPORTED

    def probe_part_months(self, attempts: int = 6) -> str:
        """Compares a month's listing with the listings of its halves, on the first months
        that have records. Returns supported / unsupported, or auto if it can't tell (then
        this run doesn't split)."""
        if not hasattr(self.connector, "chunk_keys"):
            return UNSUPPORTED
        months = [c for c in self.plan if c.period is not None][:attempts]
        for month in months:
            try:
                whole = self.connector.chunk_keys(self.entity, month)
                if not whole:
                    continue
                parts: set[str] = set()
                for half in split_period(month.period) or []:  # type: ignore[arg-type]
                    parts |= self.connector.chunk_keys(self.entity, Chunk(month.object_type, half))
            except SourceTimeoutError:
                continue
            result = SUPPORTED if parts == whole else UNSUPPORTED
            verdict = (
                "answers requests for part of a month"
                if result == SUPPORTED
                else "CAN'T answer requests for part of a month: slow months won't be split"
            )
            self.say(f"{self.label}: checked {month.label}: the source {verdict}")
            return result
        self.say(f"{self.label}: couldn't tell whether the source answers part-month requests")
        return AUTO

    # --- checkpoints, unverified ranges and slow months -------------------------------

    def _checkpoints(self, entity: SourceEntity, restart: bool) -> dict[str, int]:
        """Completed chunks (key -> records) of an interrupted full sync."""
        expired = utcnow() - CHECKPOINT_MAX_AGE
        query = delete(SyncCheckpoint).where(
            SyncCheckpoint.connection_id == self.connection_id,
            SyncCheckpoint.source_entity_key == entity.key,
        )
        if not restart:
            query = query.where(SyncCheckpoint.created_at < expired)
        self.session.execute(query)
        self.session.commit()
        return dict(
            self.session.execute(
                select(SyncCheckpoint.chunk_key, SyncCheckpoint.records).where(
                    SyncCheckpoint.connection_id == self.connection_id,
                    SyncCheckpoint.source_entity_key == entity.key,
                )
            ).all()
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

    def _reopen_unverified(
        self, entity: SourceEntity, plan: list[Chunk], done: dict[str, int]
    ) -> list[str]:
        """Chunks overlapping an open unverified range are fetched again, checkpoint or not."""
        ranges = self.session.execute(
            select(
                SyncUnverifiedRange.object_type,
                SyncUnverifiedRange.period_from,
                SyncUnverifiedRange.period_to,
            ).where(
                SyncUnverifiedRange.connection_id == self.connection_id,
                SyncUnverifiedRange.source_entity_key == entity.key,
                SyncUnverifiedRange.resolved_at.is_(None),
            )
        ).all()
        reopened = [
            chunk.key
            for chunk in plan
            if chunk.key in done
            and chunk.period is not None
            and any(
                kind == chunk.object_type
                and start <= chunk.period.end
                and chunk.period.start <= end
                for kind, start, end in ranges
            )
        ]
        for key in reopened:
            done.pop(key)
        if reopened:
            self.session.execute(
                delete(SyncCheckpoint).where(
                    SyncCheckpoint.connection_id == self.connection_id,
                    SyncCheckpoint.source_entity_key == entity.key,
                    SyncCheckpoint.chunk_key.in_(reopened),
                )
            )
            self.session.commit()
        return reopened

    def _record_unverified(self, chunk: Chunk, reason: str) -> None:
        if chunk.period is None:  # only dated chunks are verified
            return
        self.stats.unverified.append(chunk.label)
        self.session.execute(
            insert(SyncUnverifiedRange).values(
                connection_id=self.connection_id,
                source_entity_key=self.entity.key,
                object_type=chunk.object_type,
                period_from=chunk.period.start,
                period_to=chunk.period.end,
                reason=reason[:255],
                sync_run_id=self.sync_run_id,
            )
        )
        self.session.commit()
        self.say(f"{self.label}: {chunk.label} recorded as UNVERIFIED ({reason})")

    def _resolve_unverified(self, chunk: Chunk) -> None:
        """A whole chunk fetched and accepted resolves the open ranges inside it."""
        if chunk.period is None:
            return
        resolved = self.session.execute(
            update(SyncUnverifiedRange)
            .where(
                SyncUnverifiedRange.connection_id == self.connection_id,
                SyncUnverifiedRange.source_entity_key == self.entity.key,
                SyncUnverifiedRange.object_type == chunk.object_type,
                SyncUnverifiedRange.resolved_at.is_(None),
                SyncUnverifiedRange.period_from >= chunk.period.start,
                SyncUnverifiedRange.period_to <= chunk.period.end,
            )
            .values(resolved_at=utcnow(), updated_at=utcnow())
        ).rowcount
        self.session.commit()
        if resolved:
            self.say(f"{self.label}: {chunk.label}: earlier unverified range is now complete")

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
