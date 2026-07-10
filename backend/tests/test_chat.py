import base64
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api import chat as chat_module
from app.auth import create_session_cookie
from app.main import app
from app.models import (
    AudioClip,
    BugReport,
    ConversationMessage,
    OAuthToken,
    get_engine,
    init_db,
)

ALLOWED_EMAIL = "dylanr.cope@gmail.com"


@pytest.fixture(autouse=True)
def _set_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("ALLOWED_EMAIL", ALLOWED_EMAIL)
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-session-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()


@pytest.fixture()
def client():
    return TestClient(app)


def _seed_token(*, expired: bool = False) -> None:
    expires_at = datetime.now(timezone.utc) + (
        timedelta(hours=-1) if expired else timedelta(hours=1)
    )
    with Session(get_engine()) as session:
        session.add(
            OAuthToken(
                email=ALLOWED_EMAIL,
                access_token="at-original",
                refresh_token="rt-original",
                expires_at=expires_at,
            )
        )
        session.commit()


def _authed_client() -> TestClient:
    c = TestClient(app)
    c.cookies.set("session", create_session_cookie(ALLOWED_EMAIL))
    return c


def _text_only_run_turn(reply_text: str):
    async def run_turn(history, message, *, access_token=None):
        new_history = [
            *history,
            {"role": "user", "content": message},
            {"role": "assistant", "content": [{"type": "text", "text": reply_text}]},
        ]
        return {"history": new_history, "reply": reply_text}

    return run_turn


def test_post_chat_requires_auth(client):
    response = client.post("/api/chat", json={"message": "hi"})
    assert response.status_code == 401


def test_post_chat_returns_reply_and_persists_history(monkeypatch):
    _seed_token()
    monkeypatch.setattr(chat_module.agent_core, "run_turn", _text_only_run_turn("Hello Dylan!"))

    response = _authed_client().post("/api/chat", json={"message": "hi there"})

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Hello Dylan!"
    assert body["payloads"] == []

    with Session(get_engine()) as session:
        rows = session.exec(
            select(ConversationMessage).order_by(ConversationMessage.id)
        ).all()
    assert [row.role for row in rows] == ["user", "assistant"]
    assert json.loads(rows[0].content) == "hi there"
    assert json.loads(rows[1].content) == [{"type": "text", "text": "Hello Dylan!"}]


def test_post_chat_second_call_only_persists_new_messages_and_reuses_history(monkeypatch):
    _seed_token()
    captured_histories = []

    async def run_turn(history, message, *, access_token=None):
        captured_histories.append(history)
        new_history = [
            *history,
            {"role": "user", "content": message},
            {"role": "assistant", "content": [{"type": "text", "text": f"reply to {message}"}]},
        ]
        return {"history": new_history, "reply": f"reply to {message}"}

    monkeypatch.setattr(chat_module.agent_core, "run_turn", run_turn)
    authed = _authed_client()

    first = authed.post("/api/chat", json={"message": "first"})
    second = authed.post("/api/chat", json={"message": "second"})

    assert first.json()["reply"] == "reply to first"
    assert second.json()["reply"] == "reply to second"
    assert captured_histories[0] == []
    assert captured_histories[1] == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": [{"type": "text", "text": "reply to first"}]},
    ]

    with Session(get_engine()) as session:
        rows = session.exec(
            select(ConversationMessage).order_by(ConversationMessage.id)
        ).all()
    assert len(rows) == 4


def test_post_chat_extracts_audio_options_payload(monkeypatch):
    _seed_token()
    with Session(get_engine()) as session:
        clip_one = AudioClip(text="こんにちは", voice="male", audio=b"aaa")
        clip_two = AudioClip(text="こんにちは", voice="male", audio=b"bbb")
        session.add(clip_one)
        session.add(clip_two)
        session.commit()
        session.refresh(clip_one)
        session.refresh(clip_two)
        clip_ids = [clip_one.id, clip_two.id]

    async def run_turn(history, message, *, access_token=None):
        new_history = [
            *history,
            {"role": "user", "content": message},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "generate_audio",
                        "input": {"text": "こんにちは"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": json.dumps({"clip_ids": clip_ids}),
                    }
                ],
            },
            {"role": "assistant", "content": [{"type": "text", "text": "Here are 2 options."}]},
        ]
        return {"history": new_history, "reply": "Here are 2 options."}

    monkeypatch.setattr(chat_module.agent_core, "run_turn", run_turn)

    response = _authed_client().post("/api/chat", json={"message": "make audio"})

    assert response.status_code == 200
    payloads = response.json()["payloads"]
    assert payloads == [
        {
            "type": "audio_options",
            "text": "こんにちは",
            "clip_ids": clip_ids,
            "options": [
                base64.b64encode(b"aaa").decode("ascii"),
                base64.b64encode(b"bbb").decode("ascii"),
            ],
        }
    ]


def test_post_chat_extracts_card_payload(monkeypatch):
    _seed_token()

    async def run_turn(history, message, *, access_token=None):
        new_history = [
            *history,
            {"role": "user", "content": message},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-2",
                        "name": "create_anki_note",
                        "input": {
                            "deck_name": "Japanese",
                            "model_name": "Cloze",
                            "fields": {"Text": "{{c1::食べます}}"},
                            "tags": ["lesson"],
                        },
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-2",
                        "content": json.dumps({"note_id": 42}),
                    }
                ],
            },
            {"role": "assistant", "content": [{"type": "text", "text": "Card created."}]},
        ]
        return {"history": new_history, "reply": "Card created."}

    monkeypatch.setattr(chat_module.agent_core, "run_turn", run_turn)

    response = _authed_client().post("/api/chat", json={"message": "create it"})

    assert response.status_code == 200
    payloads = response.json()["payloads"]
    assert payloads == [
        {
            "type": "card",
            "deck_name": "Japanese",
            "model_name": "Cloze",
            "fields": {"Text": "{{c1::食べます}}"},
            "tags": ["lesson"],
            "note_id": 42,
        }
    ]


def test_post_chat_refreshes_expired_access_token(monkeypatch):
    _seed_token(expired=True)
    refresh_mock = AsyncMock(
        return_value={"access_token": "at-refreshed", "expires_in": 3600}
    )
    monkeypatch.setattr(chat_module.google_docs, "refresh_access_token", refresh_mock)
    monkeypatch.setattr(chat_module.agent_core, "run_turn", _text_only_run_turn("ok"))

    response = _authed_client().post("/api/chat", json={"message": "hi"})

    assert response.status_code == 200
    refresh_mock.assert_awaited_once_with("rt-original")
    with Session(get_engine()) as session:
        token = session.exec(select(OAuthToken)).one()
        assert token.access_token == "at-refreshed"


def test_post_chat_saves_bug_report_and_returns_500_without_traceback(monkeypatch):
    _seed_token()

    async def failing_run_turn(history, message, *, access_token=None):
        raise httpx.HTTPStatusError(
            "Bad response", request=httpx.Request("POST", "http://x"), response=httpx.Response(500)
        )

    monkeypatch.setattr(chat_module.agent_core, "run_turn", failing_run_turn)

    response = _authed_client().post("/api/chat", json={"message": "make audio for 食べる"})

    assert response.status_code == 500
    body = response.json()["detail"]
    assert body["error"] == "Something went wrong."
    assert "bug_report_id" in body
    assert "Traceback" not in json.dumps(body)

    with Session(get_engine()) as session:
        reports = session.exec(select(BugReport)).all()
    assert len(reports) == 1
    assert reports[0].id == body["bug_report_id"]
    assert "Bad response" in reports[0].message
    assert "Traceback" in reports[0].detail
    assert "食べる" in reports[0].detail


def test_list_bug_reports_requires_auth(client):
    response = client.get("/api/bug-reports")
    assert response.status_code == 401


def test_get_bug_report_requires_auth(client):
    response = client.get("/api/bug-reports/1")
    assert response.status_code == 401


def test_list_and_get_bug_reports(monkeypatch):
    _seed_token()

    async def failing_run_turn(history, message, *, access_token=None):
        raise ValueError("boom")

    monkeypatch.setattr(chat_module.agent_core, "run_turn", failing_run_turn)
    authed = _authed_client()
    create_response = authed.post("/api/chat", json={"message": "hi"})
    bug_report_id = create_response.json()["detail"]["bug_report_id"]

    list_response = authed.get("/api/bug-reports")
    assert list_response.status_code == 200
    listed = list_response.json()
    assert len(listed) == 1
    assert listed[0]["id"] == bug_report_id
    assert listed[0]["message"] == "boom"
    assert "detail" not in listed[0]

    get_response = authed.get(f"/api/bug-reports/{bug_report_id}")
    assert get_response.status_code == 200
    full = get_response.json()
    assert full["id"] == bug_report_id
    assert full["message"] == "boom"
    assert "Traceback" in full["detail"]


def test_get_chat_history_requires_auth(client):
    response = client.get("/api/chat/history")
    assert response.status_code == 401


def test_get_chat_history_returns_text_only_transcript(monkeypatch):
    _seed_token()

    async def run_turn(history, message, *, access_token=None):
        new_history = [
            *history,
            {"role": "user", "content": message},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "list_anki_note_types",
                        "input": {},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": json.dumps(["Cloze"]),
                    }
                ],
            },
            {"role": "assistant", "content": [{"type": "text", "text": "You have Cloze."}]},
        ]
        return {"history": new_history, "reply": "You have Cloze."}

    monkeypatch.setattr(chat_module.agent_core, "run_turn", run_turn)
    authed = _authed_client()
    authed.post("/api/chat", json={"message": "what note types do I have?"})

    response = authed.get("/api/chat/history")

    assert response.status_code == 200
    assert response.json() == [
        {"role": "user", "text": "what note types do I have?"},
        {"role": "assistant", "text": "You have Cloze."},
    ]
