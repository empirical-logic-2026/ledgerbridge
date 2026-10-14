"""The CLI outside the test environment prints counts and pass/fail only (pilot runbook)."""

import pymysql
import pytest
from sqlalchemy import Engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from connectors.tally.connector import TallyConnector
from core.config import Settings
from core.models import system as S  # noqa: N812
from core.models.base import utcnow
from tests.conftest import COMPANY
from workers import cli

# Names from the test company that must never appear in pilot output.
NAMES = (COMPANY, "Input CGST", "Rent", "Electricity", "Customer Alpha Traders")


@pytest.fixture
def run_cli(engine: Engine, connector: TallyConnector, monkeypatch: pytest.MonkeyPatch, capsys):  # noqa: ANN001, ANN201
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(cli, "connector_for", lambda session, connection: connector)
    monkeypatch.setattr(cli.registry, "create_connector", lambda code, config: connector)
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
                        "--origin", "backup", "--entity", COMPANY, "--pause")  # fmt: skip
    assert code == 0
    assert "origin backup, paused, 1 entities configured, 1 found in the source" in out

    code, out = run_cli("sync", "--connection", "tally-pilot", "--full", "--check-deletions")
    assert code == 0, out
    assert "entities: 1 entities" in out
    assert "Mapping assumptions [mapping_assumptions, LB-TRF-007]: 2" in out
    assert "PASSED" in out
    _no_names(out)

    for command in ("status", "summary"):
        code, out = run_cli(command)
        assert code == 0
        _no_names(out)
    assert "vouchers 18" in out and "Validation of entity" in out and "open alerts: none" in out

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


# --- pilot run fixes (2026-10-12) -------------------------------------------------------


def _connections(db: Session) -> list[S.Connection]:
    db.expire_all()
    return list(db.scalars(select(S.Connection)))


def test_entities_never_creates_or_changes_a_connection(db: Session, run_cli) -> None:  # noqa: ANN001
    code, out = run_cli("entities", "--connection", "tally-pilot", "--source", "tally")
    assert code == 0 and "1 entities in the source" in out
    assert _connections(db) == []

    run_cli("connect", "--connection", "tally-pilot", "--source", "tally",
            "--origin", "backup", "--entity", COMPANY)  # fmt: skip
    (before,) = _connections(db)
    snapshot = (before.status, dict(before.config), before.updated_at)
    run_cli("entities", "--connection", "tally-pilot")
    (after,) = _connections(db)
    assert (after.status, dict(after.config), after.updated_at) == snapshot


def test_new_connections_are_paused_until_activated(db: Session, run_cli) -> None:  # noqa: ANN001
    run_cli("sync", "--connection", "made-by-sync", "--source", "tally", "--no-validate")
    run_cli("connect", "--connection", "made-by-connect", "--source", "tally",
            "--origin", "backup", "--entity", COMPANY)  # fmt: skip
    assert {c.name: c.status for c in _connections(db)} == {
        "made-by-sync": "paused",
        "made-by-connect": "paused",
    }
    code, out = run_cli("connect", "--connection", "made-by-connect",
                        "--origin", "backup", "--entity", COMPANY)  # fmt: skip
    assert code == 0 and ", paused," in out  # no flag: status unchanged
    run_cli("connect", "--connection", "made-by-connect", "--origin", "backup",
            "--entity", COMPANY, "--activate")  # fmt: skip
    assert {c.name: c.status for c in _connections(db)}["made-by-connect"] == "active"
    run_cli("connect", "--connection", "made-by-connect", "--origin", "backup",
            "--entity", COMPANY, "--pause")  # fmt: skip
    assert {c.name: c.status for c in _connections(db)}["made-by-connect"] == "paused"


def test_connect_refuses_while_a_sync_runs(db: Session, run_cli) -> None:  # noqa: ANN001
    run_cli("connect", "--connection", "tally-pilot", "--source", "tally",
            "--origin", "live", "--entity", COMPANY)  # fmt: skip
    (connection,) = _connections(db)
    db.add(
        S.SyncRun(
            connection_id=connection.id, run_type="full", status="running", started_at=utcnow()
        )
    )
    db.commit()
    code, out = run_cli("connect", "--connection", "tally-pilot", "--origin", "backup",
                        "--entity", COMPANY, "--activate")  # fmt: skip
    assert code == 3 and "is running" in out and "run connect again" in out
    (after,) = _connections(db)
    assert (after.config["origin"], after.status) == ("live", "paused")


def test_unexpected_errors_outside_test_print_no_sql(
    db: Session,
    run_cli,
    monkeypatch: pytest.MonkeyPatch,  # noqa: ANN001
) -> None:
    def locked(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise OperationalError(
            "UPDATE ledgerbridge_system.connections SET config=%s WHERE id = %s",
            ('{"entities": ["Secret Client Pvt Ltd"]}', 1),
            pymysql.err.OperationalError(1205, "Lock wait timeout exceeded; try restarting"),
        )

    monkeypatch.setattr(cli, "_status", locked)
    code, out = run_cli("status")
    assert code == 1
    assert "error: OperationalError: MySQL 1205: Lock wait timeout exceeded" in out
    for leak in ("UPDATE", "SET config", "Secret Client", "parameters"):
        assert leak not in out
    with pytest.raises(OperationalError):  # the test environment keeps the full traceback
        run_cli("status", env="test")


def test_status_in_test_shows_configured_entities_stored_by_key(db: Session, run_cli) -> None:  # noqa: ANN001
    """Entities are stored as {key, name} (ADR-021); status lists their names in test."""
    run_cli("connect", "--connection", "tally-test", "--source", "tally",
            "--origin", "live", "--entity", COMPANY, "--activate", env="test")  # fmt: skip
    code, out = run_cli("status", env="test")
    assert code == 0, out
    assert f"entities: {COMPANY}" in out
    code, out = run_cli("status")  # pilot: a count
    assert code == 0 and "entities: 1 entities" in out


def test_status_and_summary_show_the_effective_timeout(db: Session, run_cli, monkeypatch) -> None:  # noqa: ANN001
    """A connection keeps its own timeout; TALLY_TIMEOUT_SEC only applies without one."""
    run_cli("connect", "--connection", "tally-pilot", "--source", "tally",
            "--origin", "backup", "--entity", COMPANY, "--timeout-sec", "120")  # fmt: skip
    monkeypatch.setenv("TALLY_TIMEOUT_SEC", "600")  # read by every Settings()
    monkeypatch.setattr(
        "workers.sync.get_settings", lambda: Settings(app_env="pilot", ai_provider="ollama")
    )
    for command in ("status", "summary"):
        code, out = run_cli(command)
        assert code == 0
        assert (
            "request timeout 120 s (set on the connection; TALLY_TIMEOUT_SEC=600 applies only "
            "to connections without one)" in out
        )
    code, out = run_cli("connect", "--connection", "tally-pilot", "--origin", "backup",
                        "--entity", COMPANY, "--timeout-sec", "600", "--pause-sec", "2",
                        "--part-month", "unsupported")  # fmt: skip
    assert "request timeout 600 s" in out and "pause between requests 2 s" in out
    assert "part-month requests: unsupported" in out
