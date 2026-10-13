"""Pilot 2026-10-13: undeclared XML prefixes from TDL customisations, a source still busy
after a timeout, syncs independent of the terminal, and interrupted runs (ADR-024)."""

import threading
import time
from datetime import date, timedelta

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from connectors.tally import parser
from connectors.tally.connector import TallyConnector
from core.config import get_settings
from core.models import system as S  # noqa: N812
from core.models.base import utcnow
from core.models.source import RawRecord
from tests.sim_tally import SimTally
from workers import cli, runs
from workers.extract import get_or_create_connection
from workers.runs import FINISHED, JobLog, RunHeartbeat, abandon_runs, reap_stale_runs
from workers.sync import SyncBusyError, run_sync

# --- 1: undeclared prefixes ---------------------------------------------------------------

UDF_RESPONSE = (
    b"<ENVELOPE><BODY><DATA><COLLECTION>"
    b'<VOUCHER REMOTEID="v-1"><GUID>v-1</GUID><ALTERID>7</ALTERID>'
    b"<NARRATION>at 10:30 a:b &lt;x:y&gt;</NARRATION>"
    b'<UDF:EXTRA.LIST UDF:INDEX="1" DESC="`Extra`"><UDF:EXTRA>Q</UDF:EXTRA></UDF:EXTRA.LIST>'
    b"<TDL:FLAG/>"
    b"</VOUCHER></COLLECTION></DATA></BODY></ENVELOPE>"
)


def test_undeclared_prefixes_parse_and_the_payload_keeps_them() -> None:
    root = parser.parse_response(UDF_RESPONSE)
    (voucher,) = parser.objects(root, "VOUCHER")
    assert parser.source_key(voucher) == "v-1" and parser.alter_id(voucher) == 7
    text = parser.payload(voucher)
    assert '<UDF:EXTRA.LIST UDF:INDEX="1" DESC="`Extra`">' in text
    assert "<UDF:EXTRA>Q</UDF:EXTRA></UDF:EXTRA.LIST>" in text
    assert "<TDL:FLAG />" in text or "<TDL:FLAG/>" in text
    assert "at 10:30 a:b &lt;x:y&gt;" in text  # text content untouched
    assert chr(0xB7) not in text


def test_undeclared_prefixes_are_reported_by_name_only() -> None:
    assert parser.undeclared_prefixes(UDF_RESPONSE) == {"UDF", "TDL"}
    assert parser.undeclared_prefixes(b"<A><B>10:30 x:y</B></A>") == set()
    assert parser.undeclared_prefixes(b'<A xml:lang="en"><xml:B/></A>') == set()


@pytest.fixture
def sim(db: Session, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    monkeypatch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )
    connection = get_or_create_connection(db, "tally-sim", "tally")
    connection.config = {**connection.config, "timeout_sec": 120}
    db.commit()

    def connector(transport: SimTally) -> TallyConnector:
        return TallyConnector.from_config(
            {"url": "http://tally.test:9000", "timeout_sec": connection.config["timeout_sec"]},
            transport=transport,
        )

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


def test_sync_with_udf_fields_succeeds_and_remembers_the_prefixes(db: Session, sim) -> None:  # noqa: ANN001
    connection, connector = sim
    transport = SimTally(per_day=1, udf=True)
    result, _, _ = _sync(db, connection, transport, connector)
    assert result.status == "succeeded", result.error
    db.refresh(connection)
    assert connection.config["xml_prefixes_seen"] == ["TDL", "UDF"]
    vouchers = db.scalars(select(RawRecord.payload).where(RawRecord.object_type == "voucher"))
    first = next(iter(vouchers))
    assert "<UDF:REFNO.LIST" in first and "</UDF:REFNO>" in first  # stored unchanged
    ledger = db.scalar(select(RawRecord.payload).where(RawRecord.object_type == "ledger"))
    assert "<UDF:CUSTOMCODE.LIST" in ledger


# --- 2: a source still busy after a timeout ---------------------------------------------


def test_waits_for_a_busy_source_after_a_timeout(db: Session, sim) -> None:  # noqa: ANN001
    connection, connector = sim
    # The whole month times out; Tally then stays busy for two more checks, and is free.
    transport = SimTally(
        per_day=1, slow_months=(date(2026, 5, 1),), slow_max_days=20, busy_after_timeout=2
    )
    result, lines, waits = _sync(db, connection, transport, connector)
    assert result.status == "succeeded", result.error
    assert waits[:2] == [10.0, 30.0]
    assert any("may still be busy with the request that timed out" in line for line in lines)
    assert any("it became free after about 40 s" in line for line in lines)
    assert not any("UNRESPONSIVE" in line for line in lines)


def test_unresponsive_only_after_waiting_as_long_as_the_timeout(db: Session, sim) -> None:  # noqa: ANN001
    connection, connector = sim
    connection.config = {**connection.config, "timeout_sec": 600}
    db.commit()
    transport = SimTally(per_day=1, dead_after=1)
    result, lines, waits = _sync(db, connection, transport, connector)
    assert result.status == "failed"
    assert sum(waits) == 600
    assert waits[:3] == [10.0, 30.0, 90.0] and max(waits) == 90.0
    (line,) = [line for line in lines if "UNRESPONSIVE" in line]
    assert "no answer for 600 s after the timeout" in line


# --- 4: interrupted and stale runs --------------------------------------------------------


def test_ctrl_c_marks_the_run_interrupted_and_keeps_checkpoints(db: Session, sim) -> None:  # noqa: ANN001
    connection, connector = sim
    transport = SimTally(per_day=1)
    original = transport._vouchers  # noqa: SLF001
    calls = {"n": 0}

    def vouchers(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        calls["n"] += 1
        if calls["n"] > 2 * 2:  # listing + vouchers for two months, then Ctrl+C
            raise KeyboardInterrupt
        return original(*args, **kwargs)

    transport._vouchers = vouchers  # noqa: SLF001
    with pytest.raises(KeyboardInterrupt):
        _sync(db, connection, transport, connector)
    run = db.scalar(select(S.SyncRun).order_by(S.SyncRun.id.desc()))
    assert run.status == "interrupted" and run.finished_at is not None
    assert "checkpoints kept" in run.error_summary
    assert db.scalar(select(func.count()).select_from(S.SyncCheckpoint)) > 0

    transport._vouchers = original  # noqa: SLF001
    result, lines, _ = _sync(db, connection, transport, connector)
    assert result.status == "succeeded", result.error
    assert any("resuming" in line for line in lines)


def _running(db: Session, connection_id: int, **values) -> S.SyncRun:  # noqa: ANN003
    now = utcnow()
    run = S.SyncRun(
        connection_id=connection_id,
        run_type="incremental",
        status="running",
        started_at=values.pop("started_at", now),
        created_at=now,
        updated_at=now,
        **values,
    )
    db.add(run)
    db.commit()
    return run


def test_stale_runs_are_marked_interrupted(db: Session, sim) -> None:  # noqa: ANN001
    connection, _ = sim
    stale_after = timedelta(seconds=get_settings().sync_stale_sec + 1)
    old = _running(db, connection.id, heartbeat_at=utcnow() - stale_after)
    fresh = _running(db, connection.id, heartbeat_at=utcnow())
    assert reap_stale_runs(db, connection.id) == [old.id]
    db.refresh(old)
    db.refresh(fresh)
    assert old.status == "interrupted" and "no heartbeat" in old.error_summary
    assert fresh.status == "running"


def test_a_run_whose_process_is_gone_is_stale_at_once(
    db: Session, sim, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    connection, _ = sim
    monkeypatch.setattr(runs, "_process_alive", lambda pid: False)
    run = _running(db, connection.id, heartbeat_at=utcnow(), pid=4242, host=runs.this_host())
    other_host = _running(db, connection.id, heartbeat_at=utcnow(), pid=4242, host="elsewhere")
    assert reap_stale_runs(db) == [run.id]
    db.refresh(other_host)
    assert other_host.status == "running"  # another machine's process: heartbeat decides


def test_a_stale_run_no_longer_blocks_a_new_sync(db: Session, sim) -> None:  # noqa: ANN001
    connection, connector = sim
    live = _running(db, connection.id, heartbeat_at=utcnow())
    with pytest.raises(SyncBusyError):
        _sync(db, connection, SimTally(per_day=1), connector)
    live.heartbeat_at = utcnow() - timedelta(seconds=get_settings().sync_stale_sec + 1)
    db.commit()
    result, _, _ = _sync(db, connection, SimTally(per_day=1), connector)
    assert result.status == "succeeded", result.error


def test_abandon_leaves_live_runs_unless_forced(db: Session, sim) -> None:  # noqa: ANN001
    connection, _ = sim
    dead = _running(db, connection.id, heartbeat_at=utcnow() - timedelta(hours=1))
    live = _running(db, connection.id, heartbeat_at=utcnow())
    assert abandon_runs(db, connection.id) == ([dead.id], [live.id])
    assert abandon_runs(db, connection.id, force=True) == ([live.id], [])
    db.refresh(live)
    assert live.status == "interrupted" and "abandoned by hand" in live.error_summary


def test_heartbeat_beats_until_stopped() -> None:
    beats: list[float] = []
    heartbeat = RunHeartbeat(lambda: beats.append(time.monotonic()), 0.01).start()
    deadline = time.monotonic() + 5
    while len(beats) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    heartbeat.stop()
    count = len(beats)
    assert count >= 3
    time.sleep(0.05)
    assert len(beats) == count
    assert not any(t.name == "sync-heartbeat" for t in threading.enumerate())
    RunHeartbeat(lambda: beats.append(0), 0).start().stop()  # 0: disabled


# --- 3: background jobs: log, watch, abandon ----------------------------------------------


@pytest.fixture
def run_cli(engine: Engine, monkeypatch: pytest.MonkeyPatch, capsys):  # noqa: ANN001, ANN201
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(cli, "_sleep", lambda seconds: None)
    monkeypatch.setattr(cli, "_terminate_raises_system_exit", lambda: None)
    transport = SimTally(per_day=1, udf=True)
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000", "timeout_sec": 120}, transport=transport
    )
    monkeypatch.setattr(cli, "connector_for", lambda session, connection: connector)
    monkeypatch.setattr(cli.registry, "create_connector", lambda code, config: connector)
    monkeypatch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )

    def run(*argv: str) -> tuple[int, str]:
        code = cli.main(list(argv))
        captured = capsys.readouterr()
        return code, captured.out + captured.err

    return run


def _log(db: Session, job: str) -> list[str]:
    db.expire_all()
    return list(
        db.scalars(select(S.SyncLog.line).where(S.SyncLog.job_id == job).order_by(S.SyncLog.id))
    )


def test_a_job_writes_its_output_and_watch_follows_it(db: Session, run_cli) -> None:  # noqa: ANN001
    code, out = run_cli("sync", "--connection", "tally-job", "--source", "tally", "--full",
                        "--no-validate", "--job", "job-1")  # fmt: skip
    assert code == 0, out
    lines = _log(db, "job-1")
    assert lines[-1] == f"{FINISHED}0]"
    assert any(line.startswith("Result") or "Result" in line for line in lines)
    assert [line for line in out.splitlines() if line] == [line for line in lines[:-1] if line]

    code, watched = run_cli("watch", "--connection", "tally-job", "--job", "job-1")
    assert code == 0
    assert "Sync job finished (exit 0)." in watched
    assert "Result" in watched

    code, latest = run_cli("watch", "--connection", "tally-job")  # the latest job by default
    assert code == 0 and "Following sync job job-1" in latest

    code, out = run_cli("summary")
    assert "XML prefixes seen in the source's data: TDL, UDF" in out


def test_watch_returns_the_jobs_exit_code(db: Session, run_cli, engine: Engine) -> None:  # noqa: ANN001
    connection = get_or_create_connection(db, "tally-job", "tally")
    db.commit()
    log = JobLog(engine, connection.id, "job-2")
    log.write("Result: failed")
    log.finish(1)
    code, out = run_cli("watch", "--connection", "tally-job", "--job", "job-2")
    assert code == 1 and "Result: failed" in out and "exit 1" in out


def test_watch_reports_a_job_whose_process_is_gone(db: Session, run_cli, engine: Engine) -> None:  # noqa: ANN001
    connection = get_or_create_connection(db, "tally-job", "tally")
    db.commit()
    JobLog(engine, connection.id, "job-3").write("fetching ...")
    code, out = run_cli("watch", "--connection", "tally-job", "--job", "job-3",
                        "--poll-sec", "1", "--grace-sec", "3")  # fmt: skip
    assert code == 1
    assert "fetching ..." in out and "stopped without finishing" in out


def test_abandon_needs_confirmation_and_spares_live_runs(db: Session, run_cli) -> None:  # noqa: ANN001
    connection = get_or_create_connection(db, "tally-job", "tally")
    db.commit()
    dead = _running(db, connection.id, heartbeat_at=utcnow() - timedelta(hours=1))
    live = _running(db, connection.id, heartbeat_at=utcnow())

    code, out = run_cli("abandon", "--connection", "tally-job")
    assert code == 2 and "needs --yes" in out
    code, out = run_cli("abandon", "--connection", "tally-job", "--yes")
    assert code == 3
    assert f"Run {dead.id} marked interrupted" in out and f"Run {live.id} still looks alive" in out
    code, out = run_cli("abandon", "--connection", "tally-job", "--yes", "--force")
    assert code == 0 and f"Run {live.id} marked interrupted" in out
    code, out = run_cli("abandon", "--connection", "tally-job", "--yes")
    assert code == 0 and "No running runs" in out
