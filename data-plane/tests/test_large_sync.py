"""Large syncs against a simulated Tally (ADR-022; pilot run 2026-10-12: Tally stopped
answering after 18 minutes and 121,124 vouchers, and the run failed)."""

from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from connectors.base import Chunk, Period, SourceEntity
from connectors.tally.client import TallyClient, TallySlowError
from connectors.tally.connector import TallyConnector
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.models.source import RawRecord
from tests.sim_tally import BOOKS_END, BOOKS_START, SimTally
from workers.extract import get_or_create_connection
from workers.fetch import ChunkFetcher, split_period
from workers.sync import load_markers, run_sync

MONTHS = 7  # April .. October 2026 (the books run to today's month)


@pytest.fixture
def sim(db: Session, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """(connection, make_connector) on a fresh SQLite database."""
    monkeypatch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )
    connection = get_or_create_connection(db, "tally-sim", "tally")
    db.commit()

    def connector(transport: SimTally) -> TallyConnector:
        return TallyConnector.from_config({"url": "http://tally.test:9000"}, transport=transport)

    return connection, connector


def _sync(db: Session, connection, transport: SimTally, connector, **kwargs):  # noqa: ANN001, ANN003, ANN202
    lines: list[str] = []
    waits: list[float] = []
    result = run_sync(
        db,
        connection,
        connector(transport),
        full=True,
        progress=lines.append,
        sleep=waits.append,
        **kwargs,
    )
    return result, lines, waits


def _count(db: Session, model: type, *where: object) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


def _raw_vouchers(db: Session) -> int:
    return _count(db, RawRecord, RawRecord.object_type == "voucher")


def _voucher_months(transport: SimTally) -> list[date]:
    return [start for kind, start, _ in transport.log if kind == "vouchers"]


# --- 1 and 2: store and checkpoint per chunk; resume ------------------------------------


def test_stops_cleanly_when_tally_stops_answering_and_resumes(db: Session, sim) -> None:  # noqa: ANN001
    connection, connector = sim
    transport = SimTally(per_day=3, dead_after=3)  # answers 3 months, then nothing
    result, lines, waits = _sync(db, connection, transport, connector)

    assert result.status == "failed"
    (outcome,) = result.entity_results
    assert outcome.status == "failed" and "SourceUnresponsiveError" in outcome.error
    # Every completed month is stored and committed: nothing held in memory and lost.
    assert _raw_vouchers(db) == (30 + 31 + 30) * 3
    assert outcome.stored == _count(db, RawRecord)  # the count matches what's stored
    assert waits == [10.0, 30.0, 90.0]  # checked with growing pauses before giving up
    assert any("UNRESPONSIVE" in line for line in lines)
    done = _count(db, S.SyncCheckpoint)
    assert done == 1 + 8 + 3  # company, 8 master types, 3 voucher months

    transport.revive()
    transport.log.clear()
    result, lines, _ = _sync(db, connection, transport, connector)
    assert result.status == "succeeded", result.error
    assert any(f"resuming: {done} of {1 + 8 + MONTHS} chunks" in line for line in lines)
    assert _voucher_months(transport) == [date(2026, m, 1) for m in (7, 8, 9, 10)]
    assert _raw_vouchers(db) == transport.total_vouchers
    assert _count(db, A.Voucher) == transport.total_vouchers  # all transformed
    assert _count(db, S.SyncCheckpoint) == 0  # done: checkpoints cleared
    entity_key = transport.guids[0]
    markers = load_markers(db, connection.id, entity_key)
    assert int(markers["voucher"]) == 10_000 + (transport.total_vouchers - 1) * 2


def test_restart_fetches_everything_again(db: Session, sim) -> None:  # noqa: ANN001
    connection, connector = sim
    transport = SimTally(per_day=1, dead_after=2)
    _sync(db, connection, transport, connector)
    transport.revive()
    transport.log.clear()
    result, lines, _ = _sync(db, connection, transport, connector, restart=True)
    assert result.status == "succeeded"
    assert not any("resuming" in line for line in lines)
    assert len(_voucher_months(transport)) == MONTHS


def test_checkpoints_expire(db: Session, sim) -> None:  # noqa: ANN001
    connection, connector = sim
    transport = SimTally(per_day=1, dead_after=2)
    _sync(db, connection, transport, connector)
    for checkpoint in db.scalars(select(S.SyncCheckpoint)):
        checkpoint.created_at -= timedelta(days=8)
    db.commit()
    transport.revive()
    transport.log.clear()
    _, lines, _ = _sync(db, connection, transport, connector)
    assert not any("resuming" in line for line in lines)
    assert len(_voucher_months(transport)) == MONTHS


# --- 3: adaptive chunking, verification, slow months remembered -----------------------


def test_slow_month_is_split_verified_and_remembered(db: Session, sim) -> None:  # noqa: ANN001
    connection, connector = sim
    may = date(2026, 5, 1)
    transport = SimTally(per_day=2, slow_months=(may,), slow_max_days=7)
    result, lines, _ = _sync(db, connection, transport, connector)
    assert result.status == "succeeded", result.error
    assert _raw_vouchers(db) == transport.total_vouchers
    may_requests = [(s, e) for kind, s, e in transport.log if kind == "vouchers" and s.month == 5]
    # month (timeout) -> 2 halves (both time out) -> weeks of at most 7 days
    assert may_requests[0] == (may, date(2026, 5, 31))
    too_large = [(s, e) for s, e in may_requests if (e - s).days + 1 > 7]
    assert too_large == [
        (may, date(2026, 5, 31)),
        (may, date(2026, 5, 16)),
        (date(2026, 5, 17), date(2026, 5, 31)),
    ]
    assert any("verified complete" in line and "2026-05-01..2026-05-31" in line for line in lines)
    assert result.entity_results[0].splits >= 1
    slow = db.scalars(select(S.SyncSlowPeriod)).one()
    assert (slow.month, slow.piece_days) == (may, 7)

    # Next full sync: May is requested in weeks straight away, without timeouts.
    transport.log.clear()
    result, lines, _ = _sync(db, connection, transport, connector, restart=True)
    assert result.status == "succeeded"
    may_requests = [(s, e) for kind, s, e in transport.log if kind == "vouchers" and s.month == 5]
    assert len(may_requests) == 5 and all((e - s).days + 1 <= 7 for s, e in may_requests)
    assert not any("timed out" in line for line in lines)


def test_parts_the_source_leaves_empty_are_caught(db: Session, sim) -> None:  # noqa: ANN001
    """Like Educational mode: sub-month requests return nothing. Verification notices."""
    connection, connector = sim
    transport = SimTally(per_day=2, max_days=20, empty_partial=True)
    result, _, _ = _sync(db, connection, transport, connector)
    (outcome,) = result.entity_results
    assert outcome.status == "failed"
    assert "IncompleteChunkError" in outcome.error and "didn't return" in outcome.error
    assert _count(db, A.Voucher) == 0  # never transformed with a gap


def test_parts_the_source_widens_are_held_to_their_dates(db: Session, sim) -> None:  # noqa: ANN001
    """Like Educational mode: a part-month request returns everything since the start of
    the books. Only each part's own dates count, so nothing is stored twice."""
    connection, connector = sim
    transport = SimTally(per_day=2, slow_months=(date(2026, 7, 1),), widen_partial=True)
    result, lines, _ = _sync(db, connection, transport, connector)
    assert result.status == "succeeded", result.error
    assert _raw_vouchers(db) == transport.total_vouchers
    assert result.entity_results[0].fetched == result.entity_results[0].stored
    assert any("2026-07-01..2026-07-31: verified complete" in line for line in lines)


def test_a_day_that_never_answers_fails_the_entity_with_a_clear_message(db: Session, sim) -> None:  # noqa: ANN001
    connection, connector = sim
    transport = SimTally(per_day=1, fail_days=(date(2026, 6, 10),))
    result, lines, _ = _sync(db, connection, transport, connector)
    (outcome,) = result.entity_results
    assert outcome.status == "failed" and "TallySlowError" in outcome.error
    assert any("can't be split further" in line for line in lines)
    assert "2026-06-10..2026-06-10" in "\n".join(lines)


def test_split_period() -> None:
    month = Period(date(2026, 5, 1), date(2026, 5, 31))
    halves = split_period(month)
    assert halves == [
        Period(date(2026, 5, 1), date(2026, 5, 16)),
        Period(date(2026, 5, 17), date(2026, 5, 31)),
    ]
    assert [p.end.day - p.start.day + 1 for p in split_period(halves[0])] == [7, 7, 2]
    assert len(split_period(Period(date(2026, 5, 1), date(2026, 5, 7)))) == 7
    assert split_period(Period(date(2026, 5, 1), date(2026, 5, 1))) is None


# --- 4: checking the source after a timeout ---------------------------------------------


class _Pinger:
    def __init__(self, answers: list[float | None]) -> None:
        self.answers = answers  # seconds per check, None = no answer
        self.now = 0.0

    def ping(self) -> None:
        answer = self.answers.pop(0)
        if answer is None:
            raise TimeoutError("no answer")
        self.now += answer

    def clock(self) -> float:
        return self.now


@pytest.mark.parametrize(
    ("answers", "expected"),
    [
        ([0.3], "responsive, so the request was too large"),
        ([42.0], "it is slow, but responding"),
        ([None, None, 1.0], "responsive"),
    ],
)
def test_source_check_reports_responsive_or_slow(
    db: Session, answers: list[float | None], expected: str
) -> None:
    expected_waits = [10.0, 30.0][: len(answers) - 1]
    pinger, lines, waits = _Pinger(answers), [], []
    fetcher = ChunkFetcher(db, 1, pinger, 1, lines.append, "entity 1 of 1",  # type: ignore[arg-type]
                           sleep=waits.append, clock=pinger.clock)  # fmt: skip
    fetcher.check_source()
    assert expected in lines[-1]
    assert waits == expected_waits


def test_client_does_not_resend_a_timed_out_request() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ReadTimeout("slow", request=request)

    client = TallyClient("http://tally.test", timeout=5, transport=httpx.MockTransport(handler))
    with pytest.raises(TallySlowError, match="within 5 s"):
        client.post("<ENVELOPE><HEADER><TALLYREQUEST>Export</TALLYREQUEST></HEADER></ENVELOPE>")
    assert calls == [1]


# --- 5: progress per chunk and a final summary ----------------------------------------


def test_progress_per_chunk_and_summary_counts(db: Session, sim) -> None:  # noqa: ANN001
    connection, connector = sim
    transport = SimTally(per_day=1)
    result, lines, _ = _sync(db, connection, transport, connector)
    assert any(
        line.startswith("entity 1 of 1: voucher 2026-04-01..2026-04-30: 30 received, 30 stored")
        for line in lines
    )
    (outcome,) = result.entity_results
    assert outcome.status == "succeeded"
    assert outcome.fetched == outcome.stored == _count(db, RawRecord)
    assert outcome.transformed == outcome.fetched - 1  # the company record goes with the entity
    assert outcome.chunks == 1 + 8 + MONTHS and outcome.chunks_skipped == 0
    assert not any("Sim Co" in line for line in lines)  # no names in progress lines


# --- 6: one entity's failure doesn't block the other -----------------------------------


def test_entities_are_transformed_and_validated_one_by_one(db: Session, sim) -> None:  # noqa: ANN001
    connection, connector = sim
    transport = SimTally(per_day=1, companies=2, fail_days=(date(2026, 6, 10),))
    validated: list[str] = []

    # Make company 1 fail (a day that never answers) and company 2 succeed.
    original = transport._vouchers

    def per_company(request, body, keys, current):  # noqa: ANN001, ANN202
        transport.fail_days = (
            {date(2026, 6, 10)} if (current and "Sim Co 1" in current.group(1)) else set()
        )
        return original(request, body, keys, current)

    transport._vouchers = per_company  # type: ignore[method-assign]
    result, lines, _ = _sync(
        db,
        connection,
        transport,
        connector,
        after_entity=lambda r, entity, changed: validated.append(entity.key),
    )
    first, second = result.entity_results
    assert (first.status, second.status) == ("failed", "succeeded")
    assert validated == [transport.guids[1]]  # validated right after its own transform
    assert result.entity_keys == [transport.guids[1]]
    assert result.status == "failed" and "1 of 2 entities failed" in result.error
    assert _count(db, A.Voucher) == transport.total_vouchers  # company 2's, transformed


# --- large synthetic data set ------------------------------------------------------------


def test_large_synthetic_company(db: Session, sim) -> None:  # noqa: ANN001
    """About 11,000 vouchers: fetched month by month, stored and transformed; no chunk is
    larger than one month."""
    connection, connector = sim
    transport = SimTally(per_day=60)
    biggest = 0
    real = TallyConnector.fetch_chunk

    def measured(self, entity: SourceEntity, chunk: Chunk, markers):  # noqa: ANN001, ANN202
        nonlocal biggest
        records = real(self, entity, chunk, markers)
        biggest = max(biggest, len(records))
        return records

    pytest.MonkeyPatch().setattr(TallyConnector, "fetch_chunk", measured)
    try:
        result, _, _ = _sync(db, connection, transport, connector)
    finally:
        pytest.MonkeyPatch().undo()
    assert result.status == "succeeded", result.error
    assert transport.total_vouchers == 183 * 60
    assert _count(db, A.Voucher) == transport.total_vouchers
    assert biggest == 31 * 60  # one month at most in memory
    assert BOOKS_START < BOOKS_END
