from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)


def test_live_reports_config_version():
    response = client.get("/api/health/live")
    assert response.status_code == 200
    assert response.json()["config_version"]


def test_ready_is_503_when_a_dependency_is_down(monkeypatch):
    async def healthy():
        return None

    async def down():
        raise ConnectionError

    monkeypatch.setattr(main, "DEPENDENCY_CHECKS", {"postgres": healthy, "qdrant": down})

    response = client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "services": {"postgres": "ok", "qdrant": "error: ConnectionError"},
    }
