from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_api_ok() -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["api"] == "ok"
