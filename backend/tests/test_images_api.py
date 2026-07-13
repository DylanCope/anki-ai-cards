import io

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.auth import create_session_cookie
from app.main import app
from app.models import ImageAsset, get_engine, init_db

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


def test_upload_image_requires_auth(client):
    response = client.post(
        "/api/images", files={"file": ("cat.png", io.BytesIO(b"pngbytes"), "image/png")}
    )
    assert response.status_code == 401


def test_upload_image_stores_it_and_returns_an_id():
    response = _authed_client().post(
        "/api/images", files={"file": ("cat.png", io.BytesIO(b"pngbytes"), "image/png")}
    )

    assert response.status_code == 200
    image_id = response.json()["image_id"]
    assert isinstance(image_id, int)

    with Session(get_engine()) as session:
        image = session.get(ImageAsset, image_id)
    assert image is not None
    assert image.data == b"pngbytes"
    assert image.content_type == "image/png"
    assert image.source == "upload"


def test_upload_image_rejects_non_image_content_type():
    response = _authed_client().post(
        "/api/images",
        files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
    )

    assert response.status_code == 400
