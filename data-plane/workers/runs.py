"""Liveness of sync runs and the output of background sync jobs (ADR-024).

- **Heartbeat:** while a run is `running`, its process updates `sync_runs.heartbeat_at`
  every SYNC_HEARTBEAT_SEC from a small background thread, also while it waits a long time
  for the source.
- **Interrupted runs:** Ctrl+C or termination marks the run `interrupted` (checkpoints are
  kept). A run left `running` whose heartbeat is older than SYNC_STALE_SEC, or whose
  process is known to be gone, has no live process: `reap_stale_runs` marks it
  `interrupted`. `abandon_runs` does that by hand.
- **Job output:** a sync started in the background writes what it prints to `sync_logs`
  under a job id, ending with a `[job finished: exit N]` line, so `sync watch` can follow
  it from any terminal.
"""

import os
import socket
import sys
import threading
from collections.abc import Callable
from datetime import timedelta
from typing import TextIO

from sqlalchemy import Engine, insert, select, update
from sqlalchemy.orm import Session

from core.config import get_settings
from core.models import SyncRun
from core.models.base import utcnow
from core.models.system import SyncLog

FINISHED = "[job finished: exit "
# Written every SYNC_HEARTBEAT_SEC while a background job runs, so `watch` can tell a job that
# is busy without printing from one whose process is gone; never shown.
ALIVE = "[job alive]"
INTERRUPTED_BY_SIGNAL = "interrupted (Ctrl+C or termination); checkpoints kept"
INTERRUPTED_STALE = "interrupted: its process is gone (no heartbeat); checkpoints kept"
INTERRUPTED_BY_HAND = "abandoned by hand (sync abandon); checkpoints kept"


def this_host() -> str:
    return socket.gethostname()[:64]


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # exists, but not ours
        return True
    except OSError:
        return True  # can't tell (e.g. Windows): rely on the heartbeat
    return True


def is_live(run: SyncRun, now=None) -> bool:  # noqa: ANN001
    """Whether a `running` run still has a live process."""
    now = now or utcnow()
    if run.host == this_host() and run.pid and not _process_alive(run.pid):
        return False
    last = run.heartbeat_at or run.started_at
    return now - last < timedelta(seconds=get_settings().sync_stale_sec)


def reap_stale_runs(session: Session, connection_id: int | None = None) -> list[int]:
    """Marks `running` runs without a live process as interrupted; returns their ids."""
    query = select(SyncRun).where(SyncRun.status == "running")
    if connection_id is not None:
        query = query.where(SyncRun.connection_id == connection_id)
    now = utcnow()
    stale = [run for run in session.scalars(query) if not is_live(run, now)]
    for run in stale:
        run.status = "interrupted"
        run.error_summary = INTERRUPTED_STALE
        run.finished_at = run.finished_at or now
    if stale:
        session.commit()
    return [run.id for run in stale]


def abandon_runs(
    session: Session, connection_id: int, force: bool = False
) -> tuple[list[int], list[int]]:
    """By hand: marks the connection's `running` runs interrupted. Runs that still look live
    are left alone unless `force`. Returns (abandoned ids, still-live ids left alone)."""
    now = utcnow()
    abandoned, live = [], []
    for run in session.scalars(
        select(SyncRun).where(SyncRun.connection_id == connection_id, SyncRun.status == "running")
    ):
        if is_live(run, now) and not force:
            live.append(run.id)
            continue
        run.status = "interrupted"
        run.error_summary = INTERRUPTED_BY_HAND
        run.finished_at = now
        abandoned.append(run.id)
    session.commit()
    return abandoned, live


class RunHeartbeat:
    """Calls `beat` every `interval` seconds on a daemon thread until stopped."""

    def __init__(self, beat: Callable[[], None], interval: float) -> None:
        self._beat = beat
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "RunHeartbeat":
        if self._interval > 0:
            self._thread = threading.Thread(target=self._loop, name="sync-heartbeat", daemon=True)
            self._thread.start()
        return self

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._beat()
            except Exception:  # noqa: BLE001, S110 - a missed beat is retried next interval
                pass

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


def heartbeat_for(engine: Engine, run_id: int) -> RunHeartbeat:
    """A heartbeat for one run, writing through its own short transactions."""

    def beat() -> None:
        with Session(engine) as session:
            session.execute(
                update(SyncRun)
                .where(SyncRun.id == run_id, SyncRun.status == "running")
                .values(heartbeat_at=utcnow())
            )
            session.commit()

    return RunHeartbeat(beat, get_settings().sync_heartbeat_sec).start()


class JobLog:
    """Writes a background job's output lines to sync_logs (own short transactions)."""

    def __init__(self, engine: Engine, connection_id: int, job_id: str) -> None:
        self.engine = engine
        self.connection_id = connection_id
        self.job_id = job_id
        self._heartbeat: RunHeartbeat | None = None

    def start_heartbeat(self) -> "JobLog":
        """Signs of life for `watch`, also for jobs without a sync run (e.g. explain)."""
        self._heartbeat = RunHeartbeat(
            lambda: self.write(ALIVE), get_settings().sync_heartbeat_sec
        ).start()
        return self

    def write(self, line: str) -> None:
        with Session(self.engine) as session:
            session.execute(
                insert(SyncLog).values(
                    connection_id=self.connection_id,
                    job_id=self.job_id,
                    logged_at=utcnow(),
                    line=line[:10_000],
                )
            )
            session.commit()

    def finish(self, code: int) -> None:
        if self._heartbeat is not None:
            self._heartbeat.stop()
        self.write(f"{FINISHED}{code}]")


class Tee:
    """A text stream that passes everything on and also sends complete lines to a JobLog."""

    def __init__(self, stream: TextIO, log: JobLog) -> None:
        self.stream = stream
        self.log = log
        self._buffer = ""

    def write(self, text: str) -> int:
        self.stream.write(text)
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            try:
                self.log.write(line)
            except Exception:  # noqa: BLE001, S110 - output must never stop the sync
                pass
        return len(text)

    def flush(self) -> None:
        self.stream.flush()

    def close_line(self) -> None:
        if self._buffer:
            self.write("\n")

    def __getattr__(self, name: str):  # noqa: ANN204 - e.g. reconfigure, isatty, encoding
        return getattr(self.stream, name)


def install_tee(log: JobLog) -> tuple[Tee, Tee]:
    out, err = Tee(sys.stdout, log), Tee(sys.stderr, log)
    sys.stdout, sys.stderr = out, err  # type: ignore[assignment]
    return out, err
