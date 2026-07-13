import pytest
from fastapi.testclient import TestClient

from app.auth import create_session_cookie
from app.main import app
from app.models import init_db

ALLOWED_EMAIL = "dylanr.cope@gmail.com"


@pytest.fixture(autouse=True)
def _set_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("ALLOWED_EMAIL", ALLOWED_EMAIL)
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-session-secret")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()


@pytest.fixture()
def client():
    return TestClient(app)


def _authed_client() -> TestClient:
    c = TestClient(app)
    c.cookies.set("session", create_session_cookie(ALLOWED_EMAIL))
    return c


def test_list_workflow_specs_requires_auth(client):
    response = client.get("/api/workflow-specs")
    assert response.status_code == 401


def test_list_workflow_specs_empty():
    response = _authed_client().get("/api/workflow-specs")
    assert response.status_code == 200
    assert response.json() == []


def test_put_creates_then_get_returns_it():
    authed = _authed_client()

    put_response = authed.put("/api/workflow-specs/lesson-doc", json={"spec": "v1"})
    assert put_response.status_code == 200
    body = put_response.json()
    assert body["name"] == "lesson-doc"
    assert body["spec"] == "v1"
    assert body["created_at"] is not None
    assert body["updated_at"] is not None

    get_response = authed.get("/api/workflow-specs/lesson-doc")
    assert get_response.status_code == 200
    assert get_response.json()["spec"] == "v1"


def test_put_is_create_or_update_by_name():
    authed = _authed_client()

    authed.put("/api/workflow-specs/lesson-doc", json={"spec": "v1"})
    updated = authed.put("/api/workflow-specs/lesson-doc", json={"spec": "v2"})
    assert updated.status_code == 200
    assert updated.json()["spec"] == "v2"

    all_specs = authed.get("/api/workflow-specs").json()
    assert len(all_specs) == 1
    assert all_specs[0]["spec"] == "v2"


def test_get_missing_workflow_spec_404s():
    response = _authed_client().get("/api/workflow-specs/does-not-exist")
    assert response.status_code == 404


def test_delete_then_get_404s():
    authed = _authed_client()
    authed.put("/api/workflow-specs/lesson-doc", json={"spec": "v1"})

    delete_response = authed.delete("/api/workflow-specs/lesson-doc")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": True}

    get_response = authed.get("/api/workflow-specs/lesson-doc")
    assert get_response.status_code == 404


def test_delete_missing_workflow_spec_404s():
    response = _authed_client().delete("/api/workflow-specs/does-not-exist")
    assert response.status_code == 404
