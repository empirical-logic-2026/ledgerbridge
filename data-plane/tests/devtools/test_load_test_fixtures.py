"""`./dev.ps1 load-test-fixtures` (devtools/load_test_fixtures.py): refuses outside the test
environment and for another company's recording, never builds a connector that could reach
Tally, and runs connect, sync, statements and validate in order."""

import json
from pathlib import Path

import pytest

from connectors import registry
from devtools import load_test_fixtures as tool


@pytest.fixture(autouse=True)
def _keep_the_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tool replaces the connector factory; put it back after each test."""
    monkeypatch.setattr(registry, "create_connector", registry.create_connector)


def _settings(monkeypatch: pytest.MonkeyPatch, env: str, port: int = tool.TEST_PORT) -> None:
    class Settings:
        app_env, mysql_port = env, port

    monkeypatch.setattr(tool, "get_settings", lambda: Settings())


@pytest.mark.parametrize(("env", "port"), [("pilot", tool.TEST_PORT), ("test", 3308)])
def test_it_refuses_outside_the_test_environment(
    monkeypatch: pytest.MonkeyPatch, env: str, port: int
) -> None:
    _settings(monkeypatch, env, port)
    ran: list[list[str]] = []
    with pytest.raises(tool.RefusedError, match="only on the test environment"):
        tool.load(tool.RECORDINGS["main"], run=lambda step: ran.append(list(step)) or 0)
    assert ran == []
    assert tool.main(["--recording", "main"]) == 2


def test_it_refuses_another_companys_recording(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _settings(monkeypatch, "test")
    (tmp_path / "manifest.json").write_text(json.dumps({"company": "Client Co", "files": {}}))
    with pytest.raises(tool.RefusedError, match="isn't LedgerBridge Test Co's"):
        tool.load(tmp_path, run=lambda step: 0)


def test_both_recordings_are_the_test_companys() -> None:
    for path in tool.RECORDINGS.values():
        assert json.loads((path / "manifest.json").read_text())["company"] == tool.COMPANY


def test_it_runs_the_steps_with_a_replaying_connector(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, "test")
    ran: list[str] = []
    printed: list[str] = []
    code = tool.load(
        tool.RECORDINGS["main"], run=lambda step: ran.append(step[0]) or 0, out=printed.append
    )
    assert code == 0
    assert ran == ["connect", "sync", "statements", "validate"]
    connector = registry.create_connector("tally", {"url": "http://tally.example:9000"})
    # The recording answers; the URL a connection holds is never used.
    assert [e.name for e in connector.list_entities()] == [tool.COMPANY]
    with pytest.raises(tool.RefusedError):
        registry.create_connector("zoho", {})


def test_a_refused_step_stops_and_problems_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, "test")
    codes = {"connect": 0, "sync": 2}
    ran: list[str] = []

    def run(step: list[str]) -> int:
        ran.append(step[0])
        return codes.get(step[0], 0)

    assert tool.load(tool.RECORDINGS["main"], run=run, out=lambda _: None) == 2
    assert ran == ["connect", "sync"]
    codes = {"validate": 1}
    assert tool.load(tool.RECORDINGS["main"], run=run, out=lambda _: None) == 1
