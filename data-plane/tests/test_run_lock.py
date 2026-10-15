"""The connection's run lock can't outlive its job (workers/locks.py; pilot 2026-10-15:
after a shutdown mid-sync, `sync full` was refused although no sync process existed)."""

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from core.models import SyncRun
from core.models import system as S  # noqa: N812
from core.models.base import utcnow
from workers import locks
from workers.extract import get_or_create_connection
from workers.runs import abandon_runs, reap_stale_runs
from workers.sync import SyncBusyError, _close_run, _interrupt_run, _open_run


@pytest.fixture
def connection(db: Session) -> S.Connection:
    connection = get_or_create_connection(db, "tally-lock", "tally")
    db.commit()
    return connection


def _key(connection: S.Connection) -> str:
    return locks.key(connection.id)


def test_a_run_holds_the_lock_until_it_ends(db, connection, lock_store) -> None:  # noqa: ANN001
    run, result = _open_run(db, connection, "full")
    assert lock_store.get(_key(connection)) == f"run:{run.id}"
    result.status = run.status = "succeeded"
    _close_run(db, run, result)
    assert lock_store.get(_key(connection)) is None


def test_an_interrupted_run_releases_the_lock(db, connection, lock_store) -> None:  # noqa: ANN001
    run, result = _open_run(db, connection, "full")
    _interrupt_run(db, run, result)
    assert run.status == "interrupted"
    assert lock_store.get(_key(connection)) is None


def test_the_lock_expires_when_its_process_dies_and_the_heartbeat_renews_it(
    db,
    connection,
    lock_store,  # noqa: ANN001
) -> None:
    run, _ = _open_run(db, connection, "full")
    ttl = locks.lock_ttl()
    assert ttl >= 90 and lock_store.ttl(_key(connection)) == ttl
    lock_store.now += ttl - 10
    locks.renew(connection.id, run.id)  # the heartbeat while the run is alive
    assert lock_store.ttl(_key(connection)) == ttl
    lock_store.now += ttl  # no heartbeat any more: the process is gone
    assert lock_store.get(_key(connection)) is None


def test_an_orphaned_lock_is_cleared_by_the_next_run(db, connection, lock_store) -> None:  # noqa: ANN001
    """The pilot case: the run was marked interrupted, but its lock survived."""
    old, _ = _open_run(db, connection, "full")
    old.status = "interrupted"
    db.commit()
    _heartbeat_stop(old.id)
    assert lock_store.get(_key(connection)) == f"run:{old.id}"
    run, _ = _open_run(db, connection, "full")  # not refused
    assert lock_store.get(_key(connection)) == f"run:{run.id}"


def test_a_lock_naming_an_unknown_run_is_orphaned(db, connection, lock_store) -> None:  # noqa: ANN001
    lock_store.set_if_absent(_key(connection), "run:999999", 600)
    run, _ = _open_run(db, connection, "full")
    assert lock_store.get(_key(connection)) == f"run:{run.id}"


def test_refused_with_a_running_run_says_which(db, connection) -> None:  # noqa: ANN001
    run, _ = _open_run(db, connection, "full")
    with pytest.raises(SyncBusyError) as busy:
        _open_run(db, connection, "incremental")
    message = str(busy.value)
    assert f"already has a sync running: run {run.id} (full)" in message
    assert "last sign of life" in message and "sync abandon" in message


def test_refused_with_only_a_lock_says_so(db, connection, lock_store) -> None:  # noqa: ANN001
    """Another process (elsewhere) is opening a run: no running run yet, only its lock."""
    lock_store.set_if_absent(_key(connection), "opening:other-host:42", 90)
    with pytest.raises(SyncBusyError) as busy:
        _open_run(db, connection, "full")
    message = str(busy.value)
    assert "has no running run, but its run lock is held" in message
    assert "expires within 90 s" in message and "sync abandon" in message


def test_the_stale_run_check_clears_the_lock(db, connection, lock_store) -> None:  # noqa: ANN001
    run, _ = _open_run(db, connection, "full")
    _heartbeat_stop(run.id)
    run.heartbeat_at = utcnow() - timedelta(hours=1)  # no sign of life since the shutdown
    run.host = "another-host"
    db.commit()
    assert reap_stale_runs(db, connection.id) == [run.id]
    assert db.get(SyncRun, run.id).status == "interrupted"
    assert lock_store.get(_key(connection)) is None


def test_the_stale_run_check_clears_an_orphaned_lock_without_a_stale_run(
    db,
    connection,
    lock_store,  # noqa: ANN001
) -> None:
    lock_store.set_if_absent(_key(connection), "run:424242", 600)
    assert reap_stale_runs(db, connection.id) == []
    assert lock_store.get(_key(connection)) is None


def test_sync_abandon_clears_the_lock(db, connection, lock_store) -> None:  # noqa: ANN001
    lock_store.set_if_absent(_key(connection), "opening:other-host:42", 90)
    assert abandon_runs(db, connection.id) == ([], [])
    assert lock_store.get(_key(connection)) is None


def test_runs_go_ahead_when_the_lock_store_is_unreachable(db, connection) -> None:  # noqa: ANN001
    class Down:
        def __getattr__(self, name: str):  # noqa: ANN204
            def fail(*args: object) -> None:
                raise ConnectionError("redis down")

            return fail

    locks.use_store(Down())  # type: ignore[arg-type]
    run, result = _open_run(db, connection, "full")  # the database check still applies
    with pytest.raises(SyncBusyError):
        _open_run(db, connection, "full")
    result.status = run.status = "succeeded"
    _close_run(db, run, result)


def _heartbeat_stop(run_id: int) -> None:
    from workers import sync

    heartbeat = sync._heartbeats.pop(run_id, None)
    if heartbeat is not None:
        heartbeat.stop()
