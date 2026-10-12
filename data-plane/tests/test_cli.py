"""The CLI outside the test environment prints counts and pass/fail only (pilot runbook)."""

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from connectors.tally.connector import TallyConnector
from core.config import Settings
from core.models import system as S  # noqa: N812
from tests.conftest import COMPANY
from workers import cli

# Names from the test company that must never appear in pilot output.
NAMES = (COMPANY, "Input CGST", "Rent", "Electricity", "Customer Alpha Traders")


@pytest.fixture
def run_cli(engine: Engine, connector: TallyConnector, monkeypatch: pytest.MonkeyPatch, capsys):  # noqa: ANN001, ANN201
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(cli, "connector_for", lambda session, connection: connector)
    monkeypatch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )

    def run(*argv: str, env: str = "pilot") -> tuple[int, str]:
        settings = Settings(app_env=env, ai_provider="ollama")
        monkeypatch.setattr(cli, "get_settings", lambda: settings)
        code = cli.main(list(argv))
        captured = capsys.readouterr()
        return code, captured.out + captured.err

    return run


def _no_names(output: str) -> None:
    for name in NAMES:
        assert name not in output, name


def test_pilot_sync_status_and_summary_print_no_names(db: Session, run_cli) -> None:  # noqa: ANN001
    code, out = run_cli("connect", "--connection", "tally-pilot", "--source", "tally",
                        "--origin", "backup", "--entity", COMPANY, "--paused")  # fmt: skip
    assert code == 0
    assert "origin backup, paused, 1 entities configured, 1 found in the source" in out

    code, out = run_cli("sync", "--connection", "tally-pilot", "--full", "--check-deletions")
    assert code == 0, out
    assert "entities: 1 entities" in out
    assert "warnings (mapping assumptions): 2" in out
    assert "PASSED" in out
    _no_names(out)

    for command in ("status", "summary"):
        code, out = run_cli(command)
        assert code == 0
        _no_names(out)
    assert "vouchers 18" in out and "validation: run" in out and "open alerts: none" in out

    connection = db.scalars(select(S.Connection)).one()
    assert (connection.status, connection.config["origin"]) == ("paused", "backup")


def test_pilot_refuses_trial_balance(db: Session, run_cli) -> None:  # noqa: ANN001
    code, out = run_cli("trial-balance", "--entity-code", "ANY")
    assert code == 2 and "test environment only" in out


def test_connect_reports_missing_entities_by_count_in_pilot(db: Session, run_cli) -> None:  # noqa: ANN001
    code, out = run_cli("connect", "--connection", "tally-pilot", "--source", "tally",
                        "--origin", "backup", "--entity", COMPANY,
                        "--entity", "Secret Client Pvt Ltd")  # fmt: skip
    assert code == 2
    assert "2 entities configured, 1 found" in out and "1 not found" in out
    assert "Secret Client" not in out


def test_test_environment_still_shows_names(db: Session, run_cli) -> None:  # noqa: ANN001
    code, out = run_cli("sync", "--connection", "tally-test", "--source", "tally",
                        "--entity", COMPANY, env="test")  # fmt: skip
    assert code == 0
    assert COMPANY in out and "Input CGST" in out
