from workers.celery_app import celery_app, ping


def test_ping_task_registered() -> None:
    assert "workers.ping" in celery_app.tasks


def test_ping_runs_eagerly() -> None:
    assert ping.apply().get() == "pong"
