from workers.celery_app import celery_app, ping


def test_ping_task_registered() -> None:
    assert "workers.ping" in celery_app.tasks


def test_ping_runs_eagerly() -> None:
    assert ping.apply().get() == "pong"


def test_failed_run_logs_no_sql(monkeypatch, caplog) -> None:  # noqa: ANN001
    """A worker error is logged as type and short message: a traceback would print SQL
    statements and their parameters."""
    import pymysql
    from sqlalchemy.exc import OperationalError

    from workers import celery_app as worker

    def failing(connection_id, runner):  # noqa: ANN001, ANN202
        raise OperationalError(
            "UPDATE ledgerbridge_system.connections SET config=%s",
            ("Secret Client Pvt Ltd",),
            pymysql.err.OperationalError(1205, "Lock wait timeout exceeded"),
        )

    monkeypatch.setattr(worker, "_run", failing)
    result = worker._locked_run(1, lambda *a: None)
    assert result == {
        "status": "error",
        "error": "OperationalError: MySQL 1205: Lock wait timeout exceeded",
    }
    assert "Lock wait timeout" in caplog.text
    assert "UPDATE" not in caplog.text and "Secret" not in caplog.text
