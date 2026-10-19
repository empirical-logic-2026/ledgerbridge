"""TallyClient: an unreachable Tally is reported as unreachable, never as slow."""

import httpx
import pytest

from connectors.tally import client as client_module
from connectors.tally.client import (
    TallyClient,
    TallyError,
    TallySlowError,
    TallyUnreachableError,
)

EXPORT = "<ENVELOPE><HEADER><TALLYREQUEST>Export</TALLYREQUEST></HEADER></ENVELOPE>"


def _client(error: type[httpx.TransportError], calls: list[int]) -> TallyClient:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise error("no answer", request=request)

    return TallyClient("http://tally.test", timeout=5, transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("error", [httpx.ConnectTimeout, httpx.ConnectError])
def test_a_tally_that_cant_be_reached_is_unreachable_not_slow(
    error: type[httpx.TransportError], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A connection that keeps failing (a connect timeout included) is retried twice, then
    reported as unreachable: the sync must not take it for a slow answer and split it."""
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: None)
    calls: list[int] = []
    with pytest.raises(TallyUnreachableError, match="not reachable") as raised:
        _client(error, calls).post(EXPORT)
    assert not isinstance(raised.value, TallySlowError)
    assert isinstance(raised.value, TallyError)  # callers catching TallyError still do
    assert len(calls) == 3


def test_a_slow_answer_is_still_slow() -> None:
    calls: list[int] = []
    with pytest.raises(TallySlowError, match="within 5 s"):
        _client(httpx.ReadTimeout, calls).post(EXPORT)
    assert calls == [1]
