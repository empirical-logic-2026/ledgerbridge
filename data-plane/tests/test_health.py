from fastapi.testclient import TestClient

from api import health
from api.main import app

client = TestClient(app)


def test_health_is_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["env"] in {"test", "pilot"}


def test_ready_reports_each_component(monkeypatch) -> None:
    monkeypatch.setattr(health, "_check_mysql", lambda: "ok")
    monkeypatch.setattr(health, "_check_redis", lambda: "ok")
    monkeypatch.setattr(health, "_check_qdrant", lambda: "failed")
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "failed",
        "mysql": "ok",
        "redis": "ok",
        "qdrant": "failed",
    }


def test_ready_ok_when_all_components_ok(monkeypatch) -> None:
    for name in ("_check_mysql", "_check_redis", "_check_qdrant"):
        monkeypatch.setattr(health, name, lambda: "ok")
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
