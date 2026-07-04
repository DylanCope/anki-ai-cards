from urllib.parse import parse_qs, urlparse

import pytest
import respx
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlmodel import Session, select

from app.auth import require_auth
from app.clients import google_docs
from app.main import app
from app.models import OAuthToken, init_db

ALLOWED_EMAIL = "dylanr.cope@gmail.com"
OTHER_EMAIL = "someone.else@gmail.com"


@pytest.fixture(autouse=True)
def _set_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("ALLOWED_EMAIL", ALLOWED_EMAIL)
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-session-secret")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://anki-ai-cards-frontend.fly.dev")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()


@pytest.fixture()
def client():
    return TestClient(app)


def _extract_state(location: str) -> str:
    return parse_qs(urlparse(location).query)["state"][0]


def test_login_redirects_to_google_and_sets_state_cookie(client):
    response = client.get("/auth/google/login", follow_redirects=False)

    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert location.startswith(google_docs.AUTH_BASE_URL)
    assert "oauth_state" in response.cookies
    assert _extract_state(location) == response.cookies["oauth_state"]


def test_login_redirect_uri_uses_public_app_url_not_request_host(client):
    # Regression test: redirect_uri must come from PUBLIC_APP_URL, never be
    # inferred from the incoming request (e.g. via request.url_for). In
    # production every request arrives via the frontend's proxy, so deriving
    # it from the request would leak the backend's private .internal address
    # to Google — which neither Google nor the browser can ever reach.
    response = client.get(
        "/auth/google/login",
        follow_redirects=False,
        headers={"host": "anki-ai-cards-backend.internal:8000"},
    )

    location = response.headers["location"]
    redirect_uri = parse_qs(urlparse(location).query)["redirect_uri"][0]
    assert redirect_uri == "https://anki-ai-cards-frontend.fly.dev/auth/google/callback"


@respx.mock
def test_callback_rejects_email_not_allowed(client):
    login_response = client.get("/auth/google/login", follow_redirects=False)
    state = _extract_state(login_response.headers["location"])

    respx.post(google_docs.TOKEN_URL).mock(
        return_value=Response(
            200,
            json={"access_token": "at-123", "refresh_token": "rt-456", "expires_in": 3600},
        )
    )
    respx.get(google_docs.USERINFO_URL).mock(
        return_value=Response(200, json={"email": OTHER_EMAIL})
    )

    response = client.get(
        "/auth/google/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert "session" not in response.cookies

    from app.models import get_engine

    with Session(get_engine()) as session:
        assert session.exec(select(OAuthToken)).first() is None


@respx.mock
def test_callback_accepts_allowed_email(client):
    login_response = client.get("/auth/google/login", follow_redirects=False)
    state = _extract_state(login_response.headers["location"])

    respx.post(google_docs.TOKEN_URL).mock(
        return_value=Response(
            200,
            json={"access_token": "at-123", "refresh_token": "rt-456", "expires_in": 3600},
        )
    )
    respx.get(google_docs.USERINFO_URL).mock(
        return_value=Response(200, json={"email": ALLOWED_EMAIL})
    )

    response = client.get(
        "/auth/google/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )

    assert response.status_code in (302, 307)
    assert "session" in response.cookies

    from app.models import get_engine

    with Session(get_engine()) as session:
        token = session.exec(select(OAuthToken)).one()
        assert token.email == ALLOWED_EMAIL
        assert token.access_token == "at-123"
        assert token.refresh_token == "rt-456"


def test_callback_rejects_mismatched_state(client):
    client.get("/auth/google/login", follow_redirects=False)

    response = client.get(
        "/auth/google/callback",
        params={"code": "auth-code", "state": "wrong-state"},
        follow_redirects=False,
    )

    assert response.status_code == 400


def test_require_auth_rejects_missing_cookie():
    protected_app = FastAPI()

    @protected_app.get("/protected")
    def protected(email: str = Depends(require_auth)):
        return {"email": email}

    response = TestClient(protected_app).get("/protected")

    assert response.status_code == 401


def test_require_auth_accepts_valid_session_cookie():
    from app.auth import SESSION_COOKIE_NAME, create_session_cookie

    protected_app = FastAPI()

    @protected_app.get("/protected")
    def protected(email: str = Depends(require_auth)):
        return {"email": email}

    protected_client = TestClient(protected_app)
    protected_client.cookies.set(SESSION_COOKIE_NAME, create_session_cookie(ALLOWED_EMAIL))

    response = protected_client.get("/protected")

    assert response.status_code == 200
    assert response.json() == {"email": ALLOWED_EMAIL}


def test_require_auth_rejects_tampered_cookie():
    from app.auth import SESSION_COOKIE_NAME

    protected_app = FastAPI()

    @protected_app.get("/protected")
    def protected(email: str = Depends(require_auth)):
        return {"email": email}

    protected_client = TestClient(protected_app)
    protected_client.cookies.set(SESSION_COOKIE_NAME, "not-a-valid-signed-token")

    response = protected_client.get("/protected")

    assert response.status_code == 401


def test_require_auth_accepts_dev_api_key(monkeypatch):
    monkeypatch.setenv("DEV_API_KEY", "test-dev-key")

    protected_app = FastAPI()

    @protected_app.get("/protected")
    def protected(email: str = Depends(require_auth)):
        return {"email": email}

    response = TestClient(protected_app).get(
        "/protected", headers={"Authorization": "Bearer test-dev-key"}
    )

    assert response.status_code == 200
    assert response.json() == {"email": ALLOWED_EMAIL}


def test_require_auth_rejects_wrong_dev_api_key(monkeypatch):
    monkeypatch.setenv("DEV_API_KEY", "test-dev-key")

    protected_app = FastAPI()

    @protected_app.get("/protected")
    def protected(email: str = Depends(require_auth)):
        return {"email": email}

    response = TestClient(protected_app).get(
        "/protected", headers={"Authorization": "Bearer wrong-key"}
    )

    assert response.status_code == 401


def test_require_auth_rejects_dev_api_key_header_when_unset():
    # DEV_API_KEY is not set by the autouse _set_env fixture, so any bearer
    # token must be rejected — the bypass must be off by default.
    protected_app = FastAPI()

    @protected_app.get("/protected")
    def protected(email: str = Depends(require_auth)):
        return {"email": email}

    response = TestClient(protected_app).get(
        "/protected", headers={"Authorization": "Bearer anything"}
    )

    assert response.status_code == 401
