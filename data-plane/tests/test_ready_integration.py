import pytest
from fastapi.testclient import TestClient

from api.main import app

pytestmark = pytest.mark.integration


def test_all_services_ready() -> None:
    """Needs the test stack (./deploy/stack.ps1 -Env test up -d) and .env.test."""
    response = TestClient(app).get("/health/ready")
    assert response.json() == {"status": "ok", "mysql": "ok", "redis": "ok", "qdrant": "ok"}
