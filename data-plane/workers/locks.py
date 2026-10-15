"""One lock per connection while a run is in progress (ADR-024; pilot 2026-10-15).

Every run (a sync, a deletion check, a transform), whether started by `dev.ps1` or by the
worker's schedule, opens through `workers.sync._open_run`, which takes this lock before it
creates its `running` row and holds it until the run ends. The lock can't outlive its job:

- **Tied to the run:** its value is the run's id (`opening:<host>:<pid>` for the moment
  before the run row exists).
- **Expires on its own:** it lives LOCK_TTL seconds (three heartbeats, at least 90 s) and
  the run's heartbeat renews it. A process that dies (a shutdown, a killed container) stops
  renewing it, so it disappears shortly after, even though Redis keeps its data on disk.
- **Released** whenever a run ends: succeeded, failed or interrupted.
- **Cleared when orphaned:** a lock whose run isn't running (or no longer has a live
  process) is removed by the stale-run check, by `sync abandon` and by the next run that
  finds it.

The database's `running` row stays the authority on whether a run is in progress; the lock
only closes the gap between two processes checking at the same moment. When Redis can't be
reached, runs go ahead on the database check alone (and say so in the log).

Pilot 2026-10-15: after a shutdown mid-sync, the next `sync full` was refused although no
process existed. The worker's lock lived two hours; runs started by `dev.ps1` took no lock
at all, so nothing could clear one either.
"""

import logging
import os
from dataclasses import dataclass
from typing import Protocol

from core.config import get_settings
from workers.runs import this_host

logger = logging.getLogger(__name__)


def key(connection_id: int) -> str:
    return f"ledgerbridge:sync:{connection_id}"


def lock_ttl() -> int:
    return max(90, int(3 * get_settings().sync_heartbeat_sec))


def opening_token() -> str:
    return f"opening:{this_host()}:{os.getpid()}"


def run_token(run_id: int) -> str:
    return f"run:{run_id}"


def run_id_of(token: str | None) -> int | None:
    if token and token.startswith("run:") and token[4:].isdigit():
        return int(token[4:])
    return None


class LockStore(Protocol):
    """The few operations the lock needs (Redis, or a stand-in in tests)."""

    def set_if_absent(self, name: str, value: str, ttl: int) -> bool: ...

    def get(self, name: str) -> str | None: ...

    def ttl(self, name: str) -> int | None: ...

    def replace_if(self, name: str, expected: str, value: str, ttl: int) -> bool: ...

    def delete_if(self, name: str, expected: str | None = None) -> bool: ...


# Compare-and-set and compare-and-delete in one step (Redis runs a script atomically).
_REPLACE = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('set', KEYS[1], ARGV[2], 'EX', ARGV[3]) and 1 else return 0 end"
)
_DELETE = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) "
    "else return 0 end"
)


class RedisLockStore:
    def __init__(self, url: str) -> None:
        from redis import Redis

        self.redis = Redis.from_url(
            url, socket_connect_timeout=3, socket_timeout=5, decode_responses=True
        )

    def set_if_absent(self, name: str, value: str, ttl: int) -> bool:
        return bool(self.redis.set(name, value, nx=True, ex=ttl))

    def get(self, name: str) -> str | None:
        return self.redis.get(name)  # type: ignore[return-value]

    def ttl(self, name: str) -> int | None:
        left = self.redis.ttl(name)
        return int(left) if isinstance(left, int) and left >= 0 else None  # type: ignore[arg-type]

    def replace_if(self, name: str, expected: str, value: str, ttl: int) -> bool:
        return bool(self.redis.eval(_REPLACE, 1, name, expected, value, ttl))

    def delete_if(self, name: str, expected: str | None = None) -> bool:
        if expected is None:
            return bool(self.redis.delete(name))
        return bool(self.redis.eval(_DELETE, 1, name, expected))


_store: LockStore | None = None


def store() -> LockStore:
    global _store
    if _store is None:
        _store = RedisLockStore(get_settings().redis_url)
    return _store


def use_store(replacement: LockStore | None) -> None:
    """Tests: a stand-in for Redis (None: back to Redis)."""
    global _store
    _store = replacement


@dataclass
class Holder:
    """Who holds a connection's lock: a run id, or a process opening one."""

    token: str
    seconds_left: int | None

    @property
    def run_id(self) -> int | None:
        return run_id_of(self.token)


def _safely(action: str, call, default):  # noqa: ANN001, ANN202
    try:
        return call()
    except Exception as exc:  # noqa: BLE001 - Redis down: the database check still applies
        logger.warning("Run lock %s skipped: %s", action, type(exc).__name__)
        return default


def acquire(connection_id: int) -> bool | None:
    """Takes the lock for a run being opened. True: taken; False: someone holds it; None:
    the lock store can't be reached (go ahead on the database check)."""
    return _safely(
        "acquire",
        lambda: store().set_if_absent(key(connection_id), opening_token(), lock_ttl()),
        None,
    )


def bind(connection_id: int, run_id: int) -> None:
    """The run row exists: the lock now names it."""
    _safely(
        "bind",
        lambda: store().replace_if(
            key(connection_id), opening_token(), run_token(run_id), lock_ttl()
        ),
        False,
    )


def renew(connection_id: int, run_id: int) -> None:
    """Called by the run's heartbeat: extends the lock while the run is alive."""
    token = run_token(run_id)
    _safely(
        "renew",
        lambda: store().replace_if(key(connection_id), token, token, lock_ttl()),
        False,
    )


def release(connection_id: int, run_id: int | None = None) -> None:
    """Releases the lock this process or run holds (never someone else's)."""
    token = run_token(run_id) if run_id is not None else opening_token()
    _safely("release", lambda: store().delete_if(key(connection_id), token), False)


def holder(connection_id: int) -> Holder | None:
    def read() -> Holder | None:
        token = store().get(key(connection_id))
        return Holder(token, store().ttl(key(connection_id))) if token else None

    return _safely("read", read, None)


def opener_gone(token: str) -> bool:
    """An `opening:<host>:<pid>` lock whose process is known to be gone (same host only;
    elsewhere the lock's expiry takes care of it)."""
    from workers.runs import _process_alive

    parts = token.split(":")
    if len(parts) != 3 or parts[0] != "opening" or parts[1] != this_host():
        return False
    return parts[2].isdigit() and not _process_alive(int(parts[2]))


def clear(connection_id: int, token: str) -> bool:
    """Removes an orphaned lock, only if it still holds `token` (no race with a new run)."""
    return _safely("clear", lambda: store().delete_if(key(connection_id), token), False)
