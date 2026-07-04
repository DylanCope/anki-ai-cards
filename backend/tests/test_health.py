from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_lifespan_creates_tables_on_a_fresh_database(tmp_path, monkeypatch):
    # Regression test: every other test module calls init_db() directly in
    # its own fixture, which masked the fact that nothing ever called it when
    # the app actually starts (real deploy hit "no such table: oauthtoken" on
    # a genuinely fresh DB file). This uses the app's lifespan for real, via
    # the context-manager form of TestClient, against a DB file with no
    # tables pre-created — the opposite of every other test's setup.
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "fresh.db"))

    from app.models import OAuthToken, get_engine

    with TestClient(app) as fresh_client:
        response = fresh_client.get("/health")
        assert response.status_code == 200

    with Session(get_engine()) as session:
        assert session.exec(select(OAuthToken)).all() == []
