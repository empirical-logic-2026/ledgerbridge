"""The Redis store behind the run lock, against the test stack's Redis (workers/locks.py)."""

import uuid

import pytest

from core.config import get_settings
from workers.locks import RedisLockStore

pytestmark = pytest.mark.integration


def test_redis_store_compare_and_set_and_expiry() -> None:
    store = RedisLockStore(get_settings().redis_url)
    name = f"ledgerbridge:test-lock:{uuid.uuid4()}"
    try:
        assert store.set_if_absent(name, "run:1", 90)
        assert not store.set_if_absent(name, "run:2", 90)  # held
        assert store.get(name) == "run:1" and 0 < (store.ttl(name) or 0) <= 90
        assert not store.replace_if(name, "run:2", "run:2", 90)  # not ours
        assert store.replace_if(name, "run:1", "run:1", 120)  # the heartbeat renews it
        assert (store.ttl(name) or 0) > 90
        assert not store.delete_if(name, "run:2")  # never someone else's
        assert store.delete_if(name, "run:1")
        assert store.get(name) is None
        assert store.set_if_absent(name, "run:3", 1)
        store.redis.pexpire(name, 1)  # a process that stopped renewing: it lapses
        import time

        time.sleep(0.05)
        assert store.get(name) is None
    finally:
        store.redis.delete(name)
