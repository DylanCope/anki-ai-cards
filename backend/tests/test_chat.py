import base64
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.agent.model_registry import DEFAULT_MODEL_ID
from app.api import chat as chat_module
from app.auth import create_session_cookie
from app.main import app
from app.models import (
    AudioClip,
    BugReport,
    Conversation,
    ConversationMessage,
    ImageAsset,
    OAuthToken,
    PendingCard,
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


def _new_conversation_id() -> int:
    with Session(get_engine()) as session:
        conversation = Conversation()
        session.add(conversation)
        session.commit()
        session.refresh(conversation)
        return conversation.id


def _text_only_run_turn(reply_text: str):
    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
        new_history = [
            *history,
            {"role": "user", "content": message},
            {"role": "assistant", "content": [{"type": "text", "text": reply_text}]},
        ]
        return {"history": new_history, "reply": reply_text}

    return run_turn


def test_post_chat_requires_auth(client):
    response = client.post("/api/chat", json={"conversation_id": 1, "message": "hi"})
    assert response.status_code == 401


def test_post_chat_404s_for_unknown_conversation(monkeypatch):
    _seed_token()
    monkeypatch.setattr(chat_module.agent_core, "run_turn", _text_only_run_turn("hi"))

    response = _authed_client().post(
        "/api/chat", json={"conversation_id": 999, "message": "hi"}
    )

    assert response.status_code == 404


def test_post_chat_returns_reply_and_persists_history(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()
    monkeypatch.setattr(chat_module.agent_core, "run_turn", _text_only_run_turn("Hello Dylan!"))

    response = _authed_client().post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "hi there"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Hello Dylan!"
    assert body["payloads"] == []

    with Session(get_engine()) as session:
        rows = session.exec(
            select(ConversationMessage).order_by(ConversationMessage.id)
        ).all()
    assert [row.role for row in rows] == ["user", "assistant"]
    assert all(row.conversation_id == conversation_id for row in rows)
    assert json.loads(rows[0].content) == "hi there"
    assert json.loads(rows[1].content) == [{"type": "text", "text": "Hello Dylan!"}]

    with Session(get_engine()) as session:
        conversation = session.get(Conversation, conversation_id)
        assert conversation.title == "hi there"


def test_post_chat_with_image_id_appends_a_machine_readable_reference(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()
    captured_messages = []

    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
        captured_messages.append(message)
        new_history = [
            *history,
            {"role": "user", "content": message},
            {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
        ]
        return {"history": new_history, "reply": "ok"}

    monkeypatch.setattr(chat_module.agent_core, "run_turn", run_turn)

    response = _authed_client().post(
        "/api/chat",
        json={
            "conversation_id": conversation_id,
            "message": "use this on the card",
            "image_id": 7,
        },
    )

    assert response.status_code == 200
    assert captured_messages == [
        "use this on the card\n\n(Attached image_id: 7 for use on a card.)"
    ]


def test_post_chat_without_image_id_leaves_message_unchanged(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()
    captured_messages = []

    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
        captured_messages.append(message)
        new_history = [
            *history,
            {"role": "user", "content": message},
            {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
        ]
        return {"history": new_history, "reply": "ok"}

    monkeypatch.setattr(chat_module.agent_core, "run_turn", run_turn)

    response = _authed_client().post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "hi there"}
    )

    assert response.status_code == 200
    assert captured_messages == ["hi there"]


def test_post_chat_with_image_id_returns_and_persists_the_attachment(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()
    with Session(get_engine()) as session:
        image = ImageAsset(content_type="image/png", data=b"upload-bytes", source="upload")
        session.add(image)
        session.commit()
        session.refresh(image)
        image_id = image.id

    monkeypatch.setattr(chat_module.agent_core, "run_turn", _text_only_run_turn("ok"))

    response = _authed_client().post(
        "/api/chat",
        json={
            "conversation_id": conversation_id,
            "message": "use this on the card",
            "image_id": image_id,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["attached_image"] == {
        "type": "image_attachment",
        "image_id": image_id,
        "data": base64.b64encode(b"upload-bytes").decode("ascii"),
        "content_type": "image/png",
    }

    with Session(get_engine()) as session:
        rows = session.exec(
            select(ConversationMessage).order_by(ConversationMessage.id)
        ).all()
    assert rows[0].role == "user"
    assert rows[0].image_id == image_id
    # Only the turn's own new user message owns the attachment — not the
    # assistant's reply persisted alongside it.
    assert rows[1].image_id is None


def test_post_chat_without_image_id_returns_no_attached_image(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()
    monkeypatch.setattr(chat_module.agent_core, "run_turn", _text_only_run_turn("ok"))

    response = _authed_client().post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "hi there"}
    )

    assert response.status_code == 200
    assert response.json()["attached_image"] is None


def test_get_chat_history_returns_image_attachment_payload_on_the_user_turn_it_was_sent_with(
    monkeypatch,
):
    _seed_token()
    conversation_id = _new_conversation_id()
    with Session(get_engine()) as session:
        image = ImageAsset(content_type="image/png", data=b"upload-bytes", source="upload")
        session.add(image)
        session.commit()
        session.refresh(image)
        image_id = image.id

    monkeypatch.setattr(chat_module.agent_core, "run_turn", _text_only_run_turn("Got it."))
    authed = _authed_client()
    authed.post(
        "/api/chat",
        json={
            "conversation_id": conversation_id,
            "message": "use this on the card",
            "image_id": image_id,
        },
    )

    response = authed.get("/api/chat/history", params={"conversation_id": conversation_id})

    assert response.status_code == 200
    assert response.json() == [
        {
            "role": "user",
            "text": "use this on the card",
            "payloads": [
                {
                    "type": "image_attachment",
                    "image_id": image_id,
                    "data": base64.b64encode(b"upload-bytes").decode("ascii"),
                    "content_type": "image/png",
                }
            ],
        },
        {"role": "assistant", "text": "Got it.", "payloads": []},
    ]


def test_post_chat_second_call_only_persists_new_messages_and_reuses_history(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()
    captured_histories = []

    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
        captured_histories.append(history)
        new_history = [
            *history,
            {"role": "user", "content": message},
            {"role": "assistant", "content": [{"type": "text", "text": f"reply to {message}"}]},
        ]
        return {"history": new_history, "reply": f"reply to {message}"}

    monkeypatch.setattr(chat_module.agent_core, "run_turn", run_turn)
    authed = _authed_client()

    first = authed.post("/api/chat", json={"conversation_id": conversation_id, "message": "first"})
    second = authed.post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "second"}
    )

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


def test_post_chat_keeps_separate_conversations_isolated(monkeypatch):
    _seed_token()
    conversation_a = _new_conversation_id()
    conversation_b = _new_conversation_id()
    captured_histories = []

    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
        captured_histories.append(history)
        new_history = [
            *history,
            {"role": "user", "content": message},
            {"role": "assistant", "content": [{"type": "text", "text": f"reply to {message}"}]},
        ]
        return {"history": new_history, "reply": f"reply to {message}"}

    monkeypatch.setattr(chat_module.agent_core, "run_turn", run_turn)
    authed = _authed_client()

    authed.post("/api/chat", json={"conversation_id": conversation_a, "message": "a1"})
    authed.post("/api/chat", json={"conversation_id": conversation_b, "message": "b1"})

    # conversation_b's turn must not see conversation_a's history.
    assert captured_histories[1] == []

    history_a = authed.get(
        "/api/chat/history", params={"conversation_id": conversation_a}
    ).json()
    history_b = authed.get(
        "/api/chat/history", params={"conversation_id": conversation_b}
    ).json()
    assert [m["text"] for m in history_a] == ["a1", "reply to a1"]
    assert [m["text"] for m in history_b] == ["b1", "reply to b1"]


def test_post_chat_extracts_audio_options_payload(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()
    with Session(get_engine()) as session:
        clip_one = AudioClip(text="こんにちは", voice="male", audio=b"aaa")
        clip_two = AudioClip(text="こんにちは", voice="male", audio=b"bbb")
        session.add(clip_one)
        session.add(clip_two)
        session.commit()
        session.refresh(clip_one)
        session.refresh(clip_two)
        clip_ids = [clip_one.id, clip_two.id]

    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
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

    response = _authed_client().post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "make audio"}
    )

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


def test_post_chat_extracts_audio_options_payload_for_search_word_pronunciations(monkeypatch):
    # Regression test: search_word_pronunciations returns the same
    # {"clip_ids": [...]} shape as generate_audio, but the extraction below
    # originally only matched on block name "generate_audio", so Forvo
    # results never got turned into a playable audio_options payload — the
    # frontend just showed clip_ids/usernames as text with no way to hear
    # them before picking.
    _seed_token()
    conversation_id = _new_conversation_id()
    with Session(get_engine()) as session:
        clip_one = AudioClip(text="猫", voice="Nekomata", audio=b"aaa", source="forvo")
        clip_two = AudioClip(text="猫", voice="Kyoko", audio=b"bbb", source="forvo")
        session.add(clip_one)
        session.add(clip_two)
        session.commit()
        session.refresh(clip_one)
        session.refresh(clip_two)
        clip_ids = [clip_one.id, clip_two.id]

    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
        new_history = [
            *history,
            {"role": "user", "content": message},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "search_word_pronunciations",
                        "input": {"word": "猫"},
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

    response = _authed_client().post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "find pronunciations"}
    )

    assert response.status_code == 200
    payloads = response.json()["payloads"]
    assert payloads == [
        {
            "type": "audio_options",
            "text": "猫",
            "clip_ids": clip_ids,
            "options": [
                base64.b64encode(b"aaa").decode("ascii"),
                base64.b64encode(b"bbb").decode("ascii"),
            ],
        }
    ]


def test_post_chat_extracts_image_options_payload_for_search_images(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()
    with Session(get_engine()) as session:
        image_one = ImageAsset(content_type="image/jpeg", data=b"aaa", source="search")
        image_two = ImageAsset(content_type="image/png", data=b"bbb", source="search")
        session.add(image_one)
        session.add(image_two)
        session.commit()
        session.refresh(image_one)
        session.refresh(image_two)
        image_ids = [image_one.id, image_two.id]

    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
        new_history = [
            *history,
            {"role": "user", "content": message},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "search_images",
                        "input": {"query": "shiba inu"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": json.dumps({"image_ids": image_ids}),
                    }
                ],
            },
            {"role": "assistant", "content": [{"type": "text", "text": "Here are 2 options."}]},
        ]
        return {"history": new_history, "reply": "Here are 2 options."}

    monkeypatch.setattr(chat_module.agent_core, "run_turn", run_turn)

    response = _authed_client().post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "find an image"}
    )

    assert response.status_code == 200
    payloads = response.json()["payloads"]
    assert payloads == [
        {
            "type": "image_options",
            "query_or_prompt": "shiba inu",
            "image_ids": image_ids,
            "options": [
                base64.b64encode(b"aaa").decode("ascii"),
                base64.b64encode(b"bbb").decode("ascii"),
            ],
            "content_types": ["image/jpeg", "image/png"],
        }
    ]


def test_post_chat_extracts_image_options_payload_for_generate_image(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()
    with Session(get_engine()) as session:
        image = ImageAsset(content_type="image/png", data=b"ccc", source="generate")
        session.add(image)
        session.commit()
        session.refresh(image)
        image_ids = [image.id]

    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
        new_history = [
            *history,
            {"role": "user", "content": message},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "generate_image",
                        "input": {"prompt": "a shiba inu wearing a hat"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": json.dumps({"image_ids": image_ids}),
                    }
                ],
            },
            {"role": "assistant", "content": [{"type": "text", "text": "Here's an option."}]},
        ]
        return {"history": new_history, "reply": "Here's an option."}

    monkeypatch.setattr(chat_module.agent_core, "run_turn", run_turn)

    response = _authed_client().post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "make an image"}
    )

    assert response.status_code == 200
    payloads = response.json()["payloads"]
    assert payloads == [
        {
            "type": "image_options",
            "query_or_prompt": "a shiba inu wearing a hat",
            "image_ids": image_ids,
            "options": [base64.b64encode(b"ccc").decode("ascii")],
            "content_types": ["image/png"],
        }
    ]


def test_post_chat_extracts_workflow_loaded_payload(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()

    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
        new_history = [
            *history,
            {"role": "user", "content": message},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "load_workflow_spec",
                        "input": {"name": "Migaku_Vocab_Mining"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": json.dumps(
                            {"name": "Migaku_Vocab_Mining", "spec": "PURPOSE\n..."}
                        ),
                    }
                ],
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Loaded the Migaku_Vocab_Mining workflow."}],
            },
        ]
        return {"history": new_history, "reply": "Loaded the Migaku_Vocab_Mining workflow."}

    monkeypatch.setattr(chat_module.agent_core, "run_turn", run_turn)

    response = _authed_client().post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "make a card for 猫"}
    )

    assert response.status_code == 200
    payloads = response.json()["payloads"]
    assert payloads == [
        {"type": "workflow_loaded", "name": "Migaku_Vocab_Mining", "spec": "PURPOSE\n..."}
    ]


def test_post_chat_extracts_no_payload_when_workflow_spec_not_found(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()

    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
        new_history = [
            *history,
            {"role": "user", "content": message},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "load_workflow_spec",
                        "input": {"name": "Nonexistent"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": json.dumps(None),
                    }
                ],
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "I couldn't find that workflow."}],
            },
        ]
        return {"history": new_history, "reply": "I couldn't find that workflow."}

    monkeypatch.setattr(chat_module.agent_core, "run_turn", run_turn)

    response = _authed_client().post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "load Nonexistent"}
    )

    assert response.status_code == 200
    assert response.json()["payloads"] == []


def test_post_chat_extracts_card_payload(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()

    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
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

    response = _authed_client().post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "create it"}
    )

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
            "status": "created",
            "pending_card_id": None,
        }
    ]


def test_post_chat_extracts_pending_card_payload(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()

    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
        new_history = [
            *history,
            {"role": "user", "content": message},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-3",
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
                        "tool_use_id": "tool-3",
                        "content": json.dumps({"pending_card_id": 7, "status": "pending"}),
                    }
                ],
            },
            {"role": "assistant", "content": [{"type": "text", "text": "Drafted."}]},
        ]
        return {"history": new_history, "reply": "Drafted."}

    monkeypatch.setattr(chat_module.agent_core, "run_turn", run_turn)

    response = _authed_client().post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "create it"}
    )

    assert response.status_code == 200
    payloads = response.json()["payloads"]
    assert payloads == [
        {
            "type": "card",
            "deck_name": "Japanese",
            "model_name": "Cloze",
            "fields": {"Text": "{{c1::食べます}}"},
            "tags": ["lesson"],
            "note_id": None,
            "status": "pending",
            "pending_card_id": 7,
        }
    ]


def test_post_chat_edit_replaces_last_user_message_and_everything_after_it(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()

    monkeypatch.setattr(chat_module.agent_core, "run_turn", _text_only_run_turn("first reply"))
    first = _authed_client().post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "first message"}
    )
    assert first.status_code == 200

    monkeypatch.setattr(chat_module.agent_core, "run_turn", _text_only_run_turn("edited reply"))
    response = _authed_client().post(
        "/api/chat",
        json={
            "conversation_id": conversation_id,
            "message": "edited message",
            "edit": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["reply"] == "edited reply"

    with Session(get_engine()) as session:
        rows = session.exec(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.id)
        ).all()
    assert [json.loads(row.content) for row in rows if row.role == "user"] == ["edited message"]
    assert len(rows) == 2
    assert json.loads(rows[1].content) == [{"type": "text", "text": "edited reply"}]


def test_post_chat_edit_rejects_when_a_card_was_already_created(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()

    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
        new_history = [
            *history,
            {"role": "user", "content": message},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
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
                        "tool_use_id": "tool-1",
                        "content": json.dumps({"note_id": 7}),
                    }
                ],
            },
            {"role": "assistant", "content": [{"type": "text", "text": "Card created."}]},
        ]
        return {"history": new_history, "reply": "Card created."}

    monkeypatch.setattr(chat_module.agent_core, "run_turn", run_turn)
    first = _authed_client().post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "create it"}
    )
    assert first.status_code == 200

    with Session(get_engine()) as session:
        rows_before = session.exec(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.id)
        ).all()
        contents_before = [(row.role, row.content) for row in rows_before]

    response = _authed_client().post(
        "/api/chat",
        json={
            "conversation_id": conversation_id,
            "message": "actually don't create it",
            "edit": True,
        },
    )

    assert response.status_code == 409

    with Session(get_engine()) as session:
        rows_after = session.exec(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.id)
        ).all()
        contents_after = [(row.role, row.content) for row in rows_after]
    assert contents_after == contents_before


def test_post_chat_edit_with_no_prior_user_message_returns_a_clean_error(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()
    monkeypatch.setattr(chat_module.agent_core, "run_turn", _text_only_run_turn("hi"))

    response = _authed_client().post(
        "/api/chat",
        json={"conversation_id": conversation_id, "message": "edited message", "edit": True},
    )

    assert response.status_code == 400


def test_post_chat_does_not_refresh_access_token_when_google_docs_not_used(monkeypatch):
    # The fix this guards: access-token resolution used to run eagerly on
    # every turn, so an unrelated dead/expired Google token could block
    # tools (like search_images) that never touch Google Docs at all.
    _seed_token(expired=True)
    conversation_id = _new_conversation_id()
    refresh_mock = AsyncMock(side_effect=AssertionError("should not be called"))
    monkeypatch.setattr(chat_module.google_docs, "refresh_access_token", refresh_mock)
    monkeypatch.setattr(chat_module.agent_core, "run_turn", _text_only_run_turn("ok"))

    response = _authed_client().post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "hi"}
    )

    assert response.status_code == 200
    refresh_mock.assert_not_awaited()


def test_post_chat_refreshes_expired_access_token_when_google_docs_used(monkeypatch):
    _seed_token(expired=True)
    conversation_id = _new_conversation_id()
    refresh_mock = AsyncMock(
        return_value={"access_token": "at-refreshed", "expires_in": 3600}
    )
    monkeypatch.setattr(chat_module.google_docs, "refresh_access_token", refresh_mock)

    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
        # Simulate the turn actually invoking fetch_google_doc, which is the
        # only tool that needs a Google token.
        token = await get_access_token()
        assert token == "at-refreshed"
        return {"history": [], "reply": "ok"}

    monkeypatch.setattr(chat_module.agent_core, "run_turn", run_turn)

    response = _authed_client().post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "hi"}
    )

    assert response.status_code == 200
    refresh_mock.assert_awaited_once_with("rt-original")
    with Session(get_engine()) as session:
        token = session.exec(select(OAuthToken)).one()
        assert token.access_token == "at-refreshed"


def test_post_chat_saves_bug_report_and_returns_500_without_traceback(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()

    async def failing_run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
        raise httpx.HTTPStatusError(
            "Bad response", request=httpx.Request("POST", "http://x"), response=httpx.Response(500)
        )

    monkeypatch.setattr(chat_module.agent_core, "run_turn", failing_run_turn)

    response = _authed_client().post(
        "/api/chat",
        json={"conversation_id": conversation_id, "message": "make audio for 食べる"},
    )

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


def test_post_chat_failure_still_persists_the_turn(monkeypatch):
    # A failed turn used to vanish entirely: nothing was saved, so the
    # user's message disappeared on the next reload with no trace of what
    # was asked or that anything had gone wrong.
    _seed_token()
    conversation_id = _new_conversation_id()

    async def failing_run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
        raise ValueError("boom")

    monkeypatch.setattr(chat_module.agent_core, "run_turn", failing_run_turn)
    authed = _authed_client()

    response = authed.post(
        "/api/chat",
        json={"conversation_id": conversation_id, "message": "make a card"},
    )
    bug_report_id = response.json()["detail"]["bug_report_id"]

    history = authed.get(
        "/api/chat/history", params={"conversation_id": conversation_id}
    ).json()
    assert history == [
        {"role": "user", "text": "make a card", "payloads": []},
        {
            "role": "assistant",
            "text": f"Something went wrong — bug report #{bug_report_id} filed.",
            "payloads": [],
        },
    ]

    with Session(get_engine()) as session:
        conversation = session.get(Conversation, conversation_id)
        assert conversation.title == "make a card"


def test_post_chat_retry_after_failure_keeps_roles_alternating(monkeypatch):
    # The Anthropic API requires alternating user/assistant turns — if a
    # failed turn only persisted the user's message (no assistant reply),
    # the next successful turn's history would end with two user messages
    # in a row.
    _seed_token()
    conversation_id = _new_conversation_id()
    captured_histories = []

    async def failing_run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
        raise ValueError("boom")

    monkeypatch.setattr(chat_module.agent_core, "run_turn", failing_run_turn)
    authed = _authed_client()
    authed.post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "first try"}
    )

    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
        captured_histories.append(history)
        return {
            "history": [
                *history,
                {"role": "user", "content": message},
                {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
            ],
            "reply": "ok",
        }

    monkeypatch.setattr(chat_module.agent_core, "run_turn", run_turn)
    authed.post("/api/chat", json={"conversation_id": conversation_id, "message": "retry"})

    roles = [m["role"] for m in captured_histories[0]]
    assert roles == ["user", "assistant"]


def test_list_bug_reports_requires_auth(client):
    response = client.get("/api/bug-reports")
    assert response.status_code == 401


def test_get_bug_report_requires_auth(client):
    response = client.get("/api/bug-reports/1")
    assert response.status_code == 401


def test_list_and_get_bug_reports(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()

    async def failing_run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
        raise ValueError("boom")

    monkeypatch.setattr(chat_module.agent_core, "run_turn", failing_run_turn)
    authed = _authed_client()
    create_response = authed.post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "hi"}
    )
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
    response = client.get("/api/chat/history", params={"conversation_id": 1})
    assert response.status_code == 401


def test_get_chat_history_404s_for_unknown_conversation():
    _seed_token()
    response = _authed_client().get("/api/chat/history", params={"conversation_id": 999})
    assert response.status_code == 404


def test_get_chat_history_returns_text_only_transcript(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()

    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
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
    authed.post(
        "/api/chat",
        json={"conversation_id": conversation_id, "message": "what note types do I have?"},
    )

    response = authed.get("/api/chat/history", params={"conversation_id": conversation_id})

    assert response.status_code == 200
    assert response.json() == [
        {"role": "user", "text": "what note types do I have?", "payloads": []},
        {"role": "assistant", "text": "You have Cloze.", "payloads": []},
    ]


def test_get_chat_history_returns_payloads_alongside_the_turn_that_produced_them(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()
    with Session(get_engine()) as session:
        clip = AudioClip(text="こんにちは", voice="male", audio=b"aaa")
        session.add(clip)
        session.commit()
        session.refresh(clip)
        clip_id = clip.id

    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
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
                        "content": json.dumps({"clip_ids": [clip_id]}),
                    }
                ],
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Here's an option."}],
            },
        ]
        return {"history": new_history, "reply": "Here's an option."}

    monkeypatch.setattr(chat_module.agent_core, "run_turn", run_turn)
    authed = _authed_client()
    authed.post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "make audio"}
    )

    # Reload history in a fresh call the way a page refresh would — this must
    # not depend on anything cached from the POST /api/chat request above.
    response = authed.get("/api/chat/history", params={"conversation_id": conversation_id})

    assert response.status_code == 200
    assert response.json() == [
        {"role": "user", "text": "make audio", "payloads": []},
        {
            "role": "assistant",
            "text": "Here's an option.",
            "payloads": [
                {
                    "type": "audio_options",
                    "text": "こんにちは",
                    "clip_ids": [clip_id],
                    "options": [base64.b64encode(b"aaa").decode("ascii")],
                }
            ],
        },
    ]


def test_get_chat_history_returns_image_options_payload_alongside_the_turn_that_produced_it(
    monkeypatch,
):
    _seed_token()
    conversation_id = _new_conversation_id()
    with Session(get_engine()) as session:
        image = ImageAsset(content_type="image/jpeg", data=b"aaa", source="search")
        session.add(image)
        session.commit()
        session.refresh(image)
        image_id = image.id

    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
        new_history = [
            *history,
            {"role": "user", "content": message},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "search_images",
                        "input": {"query": "shiba inu"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": json.dumps({"image_ids": [image_id]}),
                    }
                ],
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Here's an option."}],
            },
        ]
        return {"history": new_history, "reply": "Here's an option."}

    monkeypatch.setattr(chat_module.agent_core, "run_turn", run_turn)
    authed = _authed_client()
    authed.post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "find an image"}
    )

    response = authed.get("/api/chat/history", params={"conversation_id": conversation_id})

    assert response.status_code == 200
    assert response.json() == [
        {"role": "user", "text": "find an image", "payloads": []},
        {
            "role": "assistant",
            "text": "Here's an option.",
            "payloads": [
                {
                    "type": "image_options",
                    "query_or_prompt": "shiba inu",
                    "image_ids": [image_id],
                    "options": [base64.b64encode(b"aaa").decode("ascii")],
                    "content_types": ["image/jpeg"],
                }
            ],
        },
    ]


def test_get_chat_history_returns_card_payload_alongside_the_turn_that_produced_it(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()

    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
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
    authed = _authed_client()
    authed.post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "create it"}
    )

    response = authed.get("/api/chat/history", params={"conversation_id": conversation_id})

    assert response.status_code == 200
    assert response.json() == [
        {"role": "user", "text": "create it", "payloads": []},
        {
            "role": "assistant",
            "text": "Card created.",
            "payloads": [
                {
                    "type": "card",
                    "deck_name": "Japanese",
                    "model_name": "Cloze",
                    "fields": {"Text": "{{c1::食べます}}"},
                    "tags": ["lesson"],
                    "note_id": 42,
                    "status": "created",
                    "pending_card_id": None,
                }
            ],
        },
    ]


def test_create_conversation_requires_auth(client):
    response = client.post("/api/conversations")
    assert response.status_code == 401


def test_create_conversation(monkeypatch):
    _seed_token()
    response = _authed_client().post("/api/conversations")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] is None
    assert body["model"] == DEFAULT_MODEL_ID
    assert "id" in body and "created_at" in body and "updated_at" in body


def test_create_conversation_with_a_chosen_model():
    _seed_token()
    response = _authed_client().post("/api/conversations", json={"model": "gemini-3.1-flash-lite"})

    assert response.status_code == 200
    assert response.json()["model"] == "gemini-3.1-flash-lite"


def test_create_conversation_rejects_an_unknown_model():
    _seed_token()
    response = _authed_client().post("/api/conversations", json={"model": "gpt-4o"})

    assert response.status_code == 400


def test_update_conversation_model_requires_auth(client):
    response = client.patch("/api/conversations/1", json={"model": "gemini-3.1-flash-lite"})
    assert response.status_code == 401


def test_update_conversation_model_404s_for_unknown_conversation():
    _seed_token()
    response = _authed_client().patch(
        "/api/conversations/999", json={"model": "gemini-3.1-flash-lite"}
    )
    assert response.status_code == 404


def test_update_conversation_model_rejects_an_unknown_model():
    _seed_token()
    conversation_id = _new_conversation_id()

    response = _authed_client().patch(
        f"/api/conversations/{conversation_id}", json={"model": "gpt-4o"}
    )

    assert response.status_code == 400


def test_update_conversation_model_switches_which_provider_a_later_turn_uses(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()
    captured_model_ids = []

    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
        captured_model_ids.append(model_id)
        return {"history": [], "reply": "ok"}

    monkeypatch.setattr(chat_module.agent_core, "run_turn", run_turn)
    authed = _authed_client()

    patch_response = authed.patch(
        f"/api/conversations/{conversation_id}", json={"model": "gemini-3.1-pro-preview"}
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["model"] == "gemini-3.1-pro-preview"

    authed.post("/api/chat", json={"conversation_id": conversation_id, "message": "hi"})

    assert captured_model_ids == ["gemini-3.1-pro-preview"]


def test_update_conversation_title_renames_without_touching_model(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()

    response = _authed_client().patch(
        f"/api/conversations/{conversation_id}", json={"title": "My renamed chat"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "My renamed chat"
    assert body["model"] == DEFAULT_MODEL_ID


def test_update_conversation_title_404s_for_unknown_conversation():
    _seed_token()
    response = _authed_client().patch(
        "/api/conversations/999", json={"title": "New title"}
    )
    assert response.status_code == 404


def test_create_conversation_defaults_to_instant_creation_off():
    _seed_token()
    response = _authed_client().post("/api/conversations")

    assert response.status_code == 200
    assert response.json()["instant_creation"] is False


def test_create_conversation_with_instant_creation_on():
    _seed_token()
    response = _authed_client().post("/api/conversations", json={"instant_creation": True})

    assert response.status_code == 200
    assert response.json()["instant_creation"] is True


def test_update_conversation_instant_creation():
    _seed_token()
    conversation_id = _new_conversation_id()

    response = _authed_client().patch(
        f"/api/conversations/{conversation_id}", json={"instant_creation": True}
    )

    assert response.status_code == 200
    assert response.json()["instant_creation"] is True


def test_post_chat_passes_conversation_instant_creation_to_run_turn(monkeypatch):
    _seed_token()
    captured_instant_creation = []

    async def run_turn(history, message, *, get_access_token=None, model_id=None, instant_creation=False):
        captured_instant_creation.append(instant_creation)
        return {"history": [], "reply": "ok"}

    monkeypatch.setattr(chat_module.agent_core, "run_turn", run_turn)
    authed = _authed_client()

    create_response = authed.post("/api/conversations", json={"instant_creation": True})
    conversation_id = create_response.json()["id"]

    authed.post("/api/chat", json={"conversation_id": conversation_id, "message": "hi"})

    assert captured_instant_creation == [True]


# --- Pending-card endpoints ---


def _new_pending_card(*, status: str = "pending", tags: list[str] | None = ["lesson"]) -> int:
    with Session(get_engine()) as session:
        pending = PendingCard(
            deck_name="Japanese",
            model_name="Cloze",
            fields=json.dumps({"Text": "{{c1::食べます}}"}),
            tags=json.dumps(tags) if tags else None,
            status=status,
        )
        session.add(pending)
        session.commit()
        session.refresh(pending)
        return pending.id


def test_create_pending_card_requires_auth(client):
    response = client.post("/api/pending-cards/1/create")
    assert response.status_code == 401


def test_create_pending_card_404s_for_unknown_card():
    _seed_token()
    response = _authed_client().post("/api/pending-cards/999/create")
    assert response.status_code == 404


def test_create_pending_card_calls_ankiconnect_and_marks_created(monkeypatch):
    _seed_token()
    pending_card_id = _new_pending_card()

    create_mock = AsyncMock(return_value=99)
    monkeypatch.setattr(chat_module.agent_tools.ankiconnect, "create_note", create_mock)

    response = _authed_client().post(f"/api/pending-cards/{pending_card_id}/create")

    assert response.status_code == 200
    assert response.json() == {"note_id": 99}
    create_mock.assert_awaited_once_with(
        deck_name="Japanese",
        model_name="Cloze",
        fields={"Text": "{{c1::食べます}}"},
        tags=["lesson"],
        audio=None,
        picture=None,
    )

    with Session(get_engine()) as session:
        pending = session.get(PendingCard, pending_card_id)
    assert pending.status == "created"
    assert pending.note_id == 99


def test_create_pending_card_409s_when_not_pending(monkeypatch):
    _seed_token()
    pending_card_id = _new_pending_card(status="created")

    response = _authed_client().post(f"/api/pending-cards/{pending_card_id}/create")

    assert response.status_code == 409


def test_discard_pending_card_requires_auth(client):
    response = client.post("/api/pending-cards/1/discard")
    assert response.status_code == 401


def test_discard_pending_card_404s_for_unknown_card():
    _seed_token()
    response = _authed_client().post("/api/pending-cards/999/discard")
    assert response.status_code == 404


def test_discard_pending_card_marks_discarded():
    _seed_token()
    pending_card_id = _new_pending_card()

    response = _authed_client().post(f"/api/pending-cards/{pending_card_id}/discard")

    assert response.status_code == 200
    assert response.json() == {"status": "discarded"}
    with Session(get_engine()) as session:
        pending = session.get(PendingCard, pending_card_id)
    assert pending.status == "discarded"


def test_discard_pending_card_409s_when_not_pending():
    _seed_token()
    pending_card_id = _new_pending_card(status="discarded")

    response = _authed_client().post(f"/api/pending-cards/{pending_card_id}/discard")

    assert response.status_code == 409


def test_preview_pending_card_requires_auth(client):
    response = client.get("/api/pending-cards/1/preview")
    assert response.status_code == 401


def test_preview_pending_card_404s_for_unknown_card():
    _seed_token()
    response = _authed_client().get("/api/pending-cards/999/preview")
    assert response.status_code == 404


def test_preview_pending_card_renders_the_note_type_template(monkeypatch):
    _seed_token()
    pending_card_id = _new_pending_card(tags=None)

    templates_mock = AsyncMock(
        return_value={"Cloze": {"Front": "{{cloze:Text}}", "Back": "{{cloze:Text}}"}}
    )
    styling_mock = AsyncMock(return_value=".cloze { font-weight: bold; }")
    monkeypatch.setattr(chat_module.ankiconnect, "get_model_templates", templates_mock)
    monkeypatch.setattr(chat_module.ankiconnect, "get_model_styling", styling_mock)

    response = _authed_client().get(f"/api/pending-cards/{pending_card_id}/preview")

    assert response.status_code == 200
    body = response.json()
    templates_mock.assert_awaited_once_with("Cloze")
    styling_mock.assert_awaited_once_with("Cloze")
    assert body["css"] == ".cloze { font-weight: bold; }"
    assert "食べます" not in body["front_html"]
    assert "[...]" in body["front_html"]
    assert "食べます" in body["back_html"]


def test_delete_conversation_requires_auth(client):
    response = client.delete("/api/conversations/1")
    assert response.status_code == 401


def test_delete_conversation_404s_for_unknown_conversation():
    _seed_token()
    response = _authed_client().delete("/api/conversations/999")
    assert response.status_code == 404


def test_delete_conversation_cascades_to_delete_its_messages(monkeypatch):
    _seed_token()
    conversation_id = _new_conversation_id()
    monkeypatch.setattr(chat_module.agent_core, "run_turn", _text_only_run_turn("hi"))
    authed = _authed_client()
    authed.post("/api/chat", json={"conversation_id": conversation_id, "message": "hello"})

    with Session(get_engine()) as session:
        assert (
            len(
                session.exec(
                    select(ConversationMessage).where(
                        ConversationMessage.conversation_id == conversation_id
                    )
                ).all()
            )
            > 0
        )

    response = authed.delete(f"/api/conversations/{conversation_id}")

    assert response.status_code == 200
    assert response.json() == {"deleted": True}
    with Session(get_engine()) as session:
        assert session.get(Conversation, conversation_id) is None
        assert (
            session.exec(
                select(ConversationMessage).where(
                    ConversationMessage.conversation_id == conversation_id
                )
            ).all()
            == []
        )


def test_delete_conversation_does_not_affect_other_conversations(monkeypatch):
    _seed_token()
    conversation_a = _new_conversation_id()
    conversation_b = _new_conversation_id()
    monkeypatch.setattr(chat_module.agent_core, "run_turn", _text_only_run_turn("hi"))
    authed = _authed_client()
    authed.post("/api/chat", json={"conversation_id": conversation_b, "message": "hello"})

    authed.delete(f"/api/conversations/{conversation_a}")

    with Session(get_engine()) as session:
        assert session.get(Conversation, conversation_b) is not None
        assert (
            len(
                session.exec(
                    select(ConversationMessage).where(
                        ConversationMessage.conversation_id == conversation_b
                    )
                ).all()
            )
            > 0
        )


def test_list_models_requires_auth(client):
    response = client.get("/api/models")
    assert response.status_code == 401


def test_list_models_returns_the_catalogue():
    _seed_token()
    response = _authed_client().get("/api/models")

    assert response.status_code == 200
    listed = response.json()
    ids = {m["id"] for m in listed}
    assert DEFAULT_MODEL_ID in ids
    assert "gemini-3.1-flash-lite" in ids
    first = listed[0]
    assert {"id", "provider", "display_name", "input_price_per_mtok", "output_price_per_mtok", "description"} <= set(
        first.keys()
    )


def test_list_conversations_requires_auth(client):
    response = client.get("/api/conversations")
    assert response.status_code == 401


def test_list_conversations_orders_most_recently_updated_first(monkeypatch):
    _seed_token()
    monkeypatch.setattr(chat_module.agent_core, "run_turn", _text_only_run_turn("ok"))
    authed = _authed_client()

    older = authed.post("/api/conversations").json()
    newer = authed.post("/api/conversations").json()
    # Touch `older` after `newer` was created so it should now sort first.
    authed.post("/api/chat", json={"conversation_id": older["id"], "message": "hi"})

    listed = authed.get("/api/conversations").json()

    assert [c["id"] for c in listed] == [older["id"], newer["id"]]
    assert listed[0]["title"] == "hi"


def test_content_block_to_dict_carries_gemini_thought_signature_when_present():
    from types import SimpleNamespace

    block = SimpleNamespace(
        type="tool_use",
        id="call-1",
        name="sync_anki",
        input={},
        gemini_thought_signature="b64-opaque-bytes",
    )

    result = chat_module._content_block_to_dict(block)

    assert result["gemini_thought_signature"] == "b64-opaque-bytes"


def test_content_block_to_dict_omits_gemini_thought_signature_when_absent():
    from types import SimpleNamespace

    block = SimpleNamespace(type="tool_use", id="call-1", name="sync_anki", input={})

    result = chat_module._content_block_to_dict(block)

    assert "gemini_thought_signature" not in result
