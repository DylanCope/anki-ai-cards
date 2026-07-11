import base64
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel import Session

from app.agent import core, tools, workflow_specs
from app.models import init_db


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(tool_id: str, name: str, tool_input: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=tool_input)


def _response(stop_reason: str, content: list) -> SimpleNamespace:
    return SimpleNamespace(stop_reason=stop_reason, content=content)


def _mock_create(responses: list):
    """Build an async `messages.create` stand-in that snapshots the
    `messages` kwarg at call time (run_turn mutates its `messages` list in
    place after each call, so inspecting `call_args` afterwards would only
    show the final, fully-mutated state)."""

    remaining = list(responses)
    call_snapshots: list[dict] = []

    async def create(**kwargs):
        call_snapshots.append(copy.deepcopy(kwargs))
        return remaining.pop(0)

    return create, call_snapshots


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """A real (temp-file) SQLite DB for tests touching workflow_specs, which
    hits `app.models` directly rather than through a mocked client."""

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    return init_db()


# --- dispatch_tool: each tool routes to the right client function ---


@pytest.mark.asyncio
async def test_dispatch_fetch_google_doc(monkeypatch):
    fake_doc = {"body": {"content": []}}
    fetch_mock = AsyncMock(return_value=fake_doc)
    monkeypatch.setattr(tools.google_docs, "fetch_document", fetch_mock)
    flatten_mock = MagicMock(return_value=[{"text": "hi", "color": None}])
    monkeypatch.setattr(tools.google_docs, "flatten_runs", flatten_mock)

    result = await tools.dispatch_tool(
        "fetch_google_doc", {"document_id": "doc123"}, access_token="tok"
    )

    fetch_mock.assert_awaited_once_with("doc123", "tok")
    flatten_mock.assert_called_once_with(fake_doc)
    assert result == [{"text": "hi", "color": None}]


@pytest.mark.asyncio
async def test_dispatch_fetch_google_doc_requires_access_token():
    with pytest.raises(ValueError):
        await tools.dispatch_tool("fetch_google_doc", {"document_id": "doc123"})


@pytest.mark.asyncio
async def test_dispatch_list_anki_note_types(monkeypatch):
    mock = AsyncMock(return_value=["Basic", "Cloze"])
    monkeypatch.setattr(tools.ankiconnect, "list_note_type_names", mock)

    result = await tools.dispatch_tool("list_anki_note_types", {})

    mock.assert_awaited_once_with()
    assert result == ["Basic", "Cloze"]


@pytest.mark.asyncio
async def test_dispatch_get_anki_note_type_fields(monkeypatch):
    mock = AsyncMock(return_value=["Front", "Back"])
    monkeypatch.setattr(tools.ankiconnect, "get_note_type_fields", mock)

    result = await tools.dispatch_tool(
        "get_anki_note_type_fields", {"note_type": "Basic"}
    )

    mock.assert_awaited_once_with("Basic")
    assert result == ["Front", "Back"]


@pytest.mark.asyncio
async def test_dispatch_generate_audio(db, monkeypatch):
    mock = AsyncMock(return_value=[b"aaa", b"bbb", b"ccc"])
    monkeypatch.setattr(tools.elevenlabs, "generate_audio_options", mock)

    result = await tools.dispatch_tool("generate_audio", {"text": "こんにちは"})

    mock.assert_awaited_once_with("こんにちは", n=3, voice=tools.elevenlabs.DEFAULT_VOICE)
    # The raw audio is persisted server-side and referenced by id — never
    # sent back as part of the tool_result the model sees (see tools.py).
    assert len(result["clip_ids"]) == 3
    with Session(tools.get_engine()) as session:
        clips = [session.get(tools.AudioClip, cid) for cid in result["clip_ids"]]
    assert [c.audio for c in clips] == [b"aaa", b"bbb", b"ccc"]
    assert all(c.text == "こんにちは" for c in clips)
    assert all(c.voice == tools.elevenlabs.DEFAULT_VOICE for c in clips)


@pytest.mark.asyncio
async def test_dispatch_generate_audio_custom_n(db, monkeypatch):
    mock = AsyncMock(return_value=[b"aaa"])
    monkeypatch.setattr(tools.elevenlabs, "generate_audio_options", mock)

    await tools.dispatch_tool("generate_audio", {"text": "hi", "n": 1})

    mock.assert_awaited_once_with("hi", n=1, voice=tools.elevenlabs.DEFAULT_VOICE)


@pytest.mark.asyncio
async def test_dispatch_generate_audio_custom_voice(db, monkeypatch):
    mock = AsyncMock(return_value=[b"aaa"])
    monkeypatch.setattr(tools.elevenlabs, "generate_audio_options", mock)

    await tools.dispatch_tool("generate_audio", {"text": "hi", "voice": "female"})

    mock.assert_awaited_once_with("hi", n=3, voice="female")


@pytest.mark.asyncio
async def test_dispatch_search_images(db, monkeypatch):
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"rest-of-png"
    mock = AsyncMock(return_value=[png_bytes, b"\xff\xd8\xffjpeg-bytes"])
    monkeypatch.setattr(tools.google_image_search, "search_images", mock)

    result = await tools.dispatch_tool("search_images", {"query": "shiba inu"})

    mock.assert_awaited_once_with("shiba inu", n=3)
    assert len(result["image_ids"]) == 2
    with Session(tools.get_engine()) as session:
        images = [session.get(tools.ImageAsset, iid) for iid in result["image_ids"]]
    assert [img.data for img in images] == [png_bytes, b"\xff\xd8\xffjpeg-bytes"]
    assert [img.content_type for img in images] == ["image/png", "image/jpeg"]
    assert all(img.source == "search" for img in images)


@pytest.mark.asyncio
async def test_dispatch_search_images_custom_n(db, monkeypatch):
    mock = AsyncMock(return_value=[b"\xff\xd8\xffjpeg-bytes"])
    monkeypatch.setattr(tools.google_image_search, "search_images", mock)

    await tools.dispatch_tool("search_images", {"query": "shiba inu", "n": 1})

    mock.assert_awaited_once_with("shiba inu", n=1)


@pytest.mark.asyncio
async def test_dispatch_search_images_no_results(db, monkeypatch):
    mock = AsyncMock(return_value=[])
    monkeypatch.setattr(tools.google_image_search, "search_images", mock)

    result = await tools.dispatch_tool("search_images", {"query": "asdfqwerzxcv"})

    assert result == {"image_ids": []}


@pytest.mark.asyncio
async def test_dispatch_generate_image(db, monkeypatch):
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"rest-of-png"
    mock = AsyncMock(return_value=[png_bytes, b"\xff\xd8\xffjpeg-bytes"])
    monkeypatch.setattr(tools.gemini_images, "generate_images", mock)

    result = await tools.dispatch_tool("generate_image", {"prompt": "a shiba inu"})

    mock.assert_awaited_once_with("a shiba inu", n=3)
    assert len(result["image_ids"]) == 2
    with Session(tools.get_engine()) as session:
        images = [session.get(tools.ImageAsset, iid) for iid in result["image_ids"]]
    assert [img.data for img in images] == [png_bytes, b"\xff\xd8\xffjpeg-bytes"]
    assert [img.content_type for img in images] == ["image/png", "image/jpeg"]
    assert all(img.source == "generate" for img in images)


@pytest.mark.asyncio
async def test_dispatch_generate_image_custom_n(db, monkeypatch):
    mock = AsyncMock(return_value=[b"\xff\xd8\xffjpeg-bytes"])
    monkeypatch.setattr(tools.gemini_images, "generate_images", mock)

    await tools.dispatch_tool("generate_image", {"prompt": "a shiba inu", "n": 1})

    mock.assert_awaited_once_with("a shiba inu", n=1)


@pytest.mark.asyncio
async def test_dispatch_generate_image_api_error_propagates(db, monkeypatch):
    mock = AsyncMock(side_effect=tools.gemini_images.GeminiImageError("boom"))
    monkeypatch.setattr(tools.gemini_images, "generate_images", mock)

    with pytest.raises(tools.gemini_images.GeminiImageError):
        await tools.dispatch_tool("generate_image", {"prompt": "a shiba inu"})


@pytest.mark.asyncio
async def test_dispatch_create_anki_note(monkeypatch):
    mock = AsyncMock(return_value=12345)
    monkeypatch.setattr(tools.ankiconnect, "create_note", mock)

    result = await tools.dispatch_tool(
        "create_anki_note",
        {
            "deck_name": "Japanese",
            "model_name": "Cloze",
            "fields": {"Text": "{{c1::食べる}}"},
            "tags": ["lesson"],
        },
    )

    mock.assert_awaited_once_with(
        deck_name="Japanese",
        model_name="Cloze",
        fields={"Text": "{{c1::食べる}}"},
        tags=["lesson"],
        audio=None,
        picture=None,
    )
    assert result == {"note_id": 12345}


@pytest.mark.asyncio
async def test_dispatch_create_anki_note_attaches_picked_audio_clip(db, monkeypatch):
    generate_mock = AsyncMock(return_value=[b"aaa", b"bbb"])
    monkeypatch.setattr(tools.elevenlabs, "generate_audio_options", generate_mock)
    generated = await tools.dispatch_tool("generate_audio", {"text": "食べる"})
    picked_clip_id = generated["clip_ids"][1]

    create_mock = AsyncMock(return_value=12345)
    monkeypatch.setattr(tools.ankiconnect, "create_note", create_mock)

    result = await tools.dispatch_tool(
        "create_anki_note",
        {
            "deck_name": "Japanese",
            "model_name": "Cloze+",
            "fields": {"Text": "{{c1::食べる}}"},
            "audio": {"clip_id": picked_clip_id, "fields": ["Text Audio"]},
        },
    )

    create_mock.assert_awaited_once_with(
        deck_name="Japanese",
        model_name="Cloze+",
        fields={"Text": "{{c1::食べる}}"},
        tags=None,
        audio={
            "data": base64.b64encode(b"bbb").decode("ascii"),
            "filename": f"anki-ai-cards-{picked_clip_id}.mp3",
            "fields": ["Text Audio"],
        },
        picture=None,
    )
    assert result == {"note_id": 12345}


@pytest.mark.asyncio
async def test_dispatch_create_anki_note_rejects_unknown_audio_clip(db):
    with pytest.raises(ValueError, match="Unknown audio clip_id"):
        await tools.dispatch_tool(
            "create_anki_note",
            {
                "deck_name": "Japanese",
                "model_name": "Cloze+",
                "fields": {"Text": "{{c1::食べる}}"},
                "audio": {"clip_id": 999, "fields": ["Text Audio"]},
            },
        )


@pytest.mark.asyncio
async def test_dispatch_create_anki_note_attaches_picked_image(db, monkeypatch):
    with Session(tools.get_engine()) as session:
        image = tools.ImageAsset(content_type="image/png", data=b"pngbytes", source="upload")
        session.add(image)
        session.commit()
        session.refresh(image)
        image_id = image.id

    create_mock = AsyncMock(return_value=12345)
    monkeypatch.setattr(tools.ankiconnect, "create_note", create_mock)

    result = await tools.dispatch_tool(
        "create_anki_note",
        {
            "deck_name": "Japanese",
            "model_name": "Cloze+",
            "fields": {"Text": "{{c1::食べる}}"},
            "picture": {"image_id": image_id, "fields": ["Picture"]},
        },
    )

    create_mock.assert_awaited_once_with(
        deck_name="Japanese",
        model_name="Cloze+",
        fields={"Text": "{{c1::食べる}}"},
        tags=None,
        audio=None,
        picture={
            "data": base64.b64encode(b"pngbytes").decode("ascii"),
            "filename": f"anki-ai-cards-{image_id}.png",
            "fields": ["Picture"],
        },
    )
    assert result == {"note_id": 12345}


@pytest.mark.asyncio
async def test_dispatch_create_anki_note_rejects_unknown_image_id(db):
    with pytest.raises(ValueError, match="Unknown image image_id"):
        await tools.dispatch_tool(
            "create_anki_note",
            {
                "deck_name": "Japanese",
                "model_name": "Cloze+",
                "fields": {"Text": "{{c1::食べる}}"},
                "picture": {"image_id": 999, "fields": ["Picture"]},
            },
        )


@pytest.mark.asyncio
async def test_dispatch_sync_anki(monkeypatch):
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(tools.ankiconnect, "sync", mock)

    result = await tools.dispatch_tool("sync_anki", {})

    mock.assert_awaited_once_with()
    assert result == {"synced": True}


@pytest.mark.asyncio
async def test_dispatch_save_workflow_spec(db):
    result = await tools.dispatch_tool(
        "save_workflow_spec", {"name": "lesson-doc", "spec": "spec content"}
    )

    assert result == {"name": "lesson-doc", "spec": "spec content"}
    assert workflow_specs.load_workflow_spec("lesson-doc").spec == "spec content"


@pytest.mark.asyncio
async def test_dispatch_load_workflow_spec(db):
    workflow_specs.save_workflow_spec("lesson-doc", "spec content")

    result = await tools.dispatch_tool("load_workflow_spec", {"name": "lesson-doc"})

    assert result == {"name": "lesson-doc", "spec": "spec content"}


@pytest.mark.asyncio
async def test_dispatch_load_workflow_spec_missing(db):
    result = await tools.dispatch_tool("load_workflow_spec", {"name": "nope"})

    assert result is None


@pytest.mark.asyncio
async def test_dispatch_list_workflow_specs(db):
    workflow_specs.save_workflow_spec("lesson-doc", "a")
    workflow_specs.save_workflow_spec("other-source", "b")

    result = await tools.dispatch_tool("list_workflow_specs", {})

    assert sorted(result) == ["lesson-doc", "other-source"]


@pytest.mark.asyncio
async def test_dispatch_unknown_tool():
    with pytest.raises(ValueError):
        await tools.dispatch_tool("not_a_real_tool", {})


# --- run_turn: drives the tool-use loop against a mocked anthropic client ---


@pytest.mark.asyncio
async def test_run_turn_no_tool_use(db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    create, call_snapshots = _mock_create(
        [_response("end_turn", [_text_block("Hello Dylan!")])]
    )
    client = AsyncMock()
    client.messages.create = create

    with patch("app.agent.providers.anthropic_provider.anthropic.AsyncAnthropic", return_value=client):
        result = await core.run_turn([], "hi", model_id="claude-opus-4-8")

    assert result["reply"] == "Hello Dylan!"
    assert len(call_snapshots) == 1
    kwargs = call_snapshots[0]
    assert kwargs["model"] == "claude-opus-4-8"
    assert kwargs["tools"] == tools.TOOL_SCHEMAS
    assert kwargs["messages"][-1] == {"role": "user", "content": "hi"}


@pytest.mark.asyncio
async def test_run_turn_one_tool_call_then_end_turn(db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    list_mock = AsyncMock(return_value=["Basic", "Cloze"])
    monkeypatch.setattr(tools.ankiconnect, "list_note_type_names", list_mock)

    tool_use_response = _response(
        "tool_use",
        [
            _text_block("Let me check your note types."),
            _tool_use_block("toolu_1", "list_anki_note_types", {}),
        ],
    )
    end_turn_response = _response(
        "end_turn", [_text_block("You have a Cloze note type.")]
    )

    create, call_snapshots = _mock_create([tool_use_response, end_turn_response])
    client = AsyncMock()
    client.messages.create = create

    with patch("app.agent.providers.anthropic_provider.anthropic.AsyncAnthropic", return_value=client):
        result = await core.run_turn([], "what note types do I have?", model_id="claude-opus-4-8")

    list_mock.assert_awaited_once_with()
    assert result["reply"] == "You have a Cloze note type."
    assert len(call_snapshots) == 2

    # The tool_result sent back on the second call carries the tool's output
    # keyed to the matching tool_use_id.
    second_call_messages = call_snapshots[1]["messages"]
    tool_result_message = second_call_messages[-1]
    assert tool_result_message["role"] == "user"
    tool_result = tool_result_message["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "toolu_1"
    assert json.loads(tool_result["content"]) == ["Basic", "Cloze"]


@pytest.mark.asyncio
async def test_run_turn_passes_access_token_to_tools(db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    fetch_mock = AsyncMock(return_value={"body": {"content": []}})
    monkeypatch.setattr(tools.google_docs, "fetch_document", fetch_mock)
    monkeypatch.setattr(tools.google_docs, "flatten_runs", lambda doc: [])

    tool_use_response = _response(
        "tool_use",
        [_tool_use_block("toolu_2", "fetch_google_doc", {"document_id": "abc"})],
    )
    end_turn_response = _response("end_turn", [_text_block("done")])

    client = AsyncMock()
    client.messages.create = AsyncMock(
        side_effect=[tool_use_response, end_turn_response]
    )

    with patch("app.agent.providers.anthropic_provider.anthropic.AsyncAnthropic", return_value=client):
        await core.run_turn([], "read the doc", access_token="tok-xyz", model_id="claude-opus-4-8")

    fetch_mock.assert_awaited_once_with("abc", "tok-xyz")


@pytest.mark.asyncio
async def test_run_turn_recovers_from_a_failing_tool_call(db, monkeypatch):
    # A tool raising must not crash the whole turn — it should come back as
    # an `is_error` tool_result so Claude can explain the failure to Dylan
    # (or retry/ask a follow-up) instead of the chat API 500ing with no
    # assistant reply at all.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    list_mock = AsyncMock(side_effect=tools.ankiconnect.AnkiConnectError("timed out"))
    monkeypatch.setattr(tools.ankiconnect, "list_note_type_names", list_mock)

    tool_use_response = _response(
        "tool_use",
        [_tool_use_block("toolu_3", "list_anki_note_types", {})],
    )
    end_turn_response = _response(
        "end_turn",
        [_text_block("I couldn't reach Anki just now — want me to try again?")],
    )

    create, call_snapshots = _mock_create([tool_use_response, end_turn_response])
    client = AsyncMock()
    client.messages.create = create

    with patch("app.agent.providers.anthropic_provider.anthropic.AsyncAnthropic", return_value=client):
        result = await core.run_turn([], "what note types do I have?", model_id="claude-opus-4-8")

    assert result["reply"] == "I couldn't reach Anki just now — want me to try again?"
    assert len(call_snapshots) == 2

    second_call_messages = call_snapshots[1]["messages"]
    tool_result = second_call_messages[-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "toolu_3"
    assert tool_result["is_error"] is True
    assert "timed out" in tool_result["content"]


@pytest.mark.asyncio
async def test_run_turn_routes_to_the_gemini_provider_for_a_gemini_model(db, monkeypatch):
    # run_turn must pick the provider adapter matching model_id's registry
    # entry, not always Anthropic — this is the whole point of model
    # selection. Patching gemini_provider.create_message directly (rather
    # than mocking the underlying google-genai client, covered in
    # test_gemini_provider.py) isolates core.py's provider-dispatch logic.
    gemini_create = AsyncMock(
        return_value=_response("end_turn", [_text_block("Konnichiwa!")])
    )
    monkeypatch.setattr(core.gemini_provider, "create_message", gemini_create)
    anthropic_create = AsyncMock()
    monkeypatch.setattr(core.anthropic_provider, "create_message", anthropic_create)

    result = await core.run_turn([], "hi", model_id="gemini-3.1-flash-lite")

    assert result["reply"] == "Konnichiwa!"
    gemini_create.assert_awaited_once()
    assert gemini_create.await_args.kwargs["model_id"] == "gemini-3.1-flash-lite"
    anthropic_create.assert_not_awaited()


# --- known workflow specs are surfaced at the start of a conversation ---


@pytest.mark.asyncio
async def test_run_turn_surfaces_known_specs_on_empty_history(db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    workflow_specs.save_workflow_spec("lesson-doc", "spec content")

    create, call_snapshots = _mock_create(
        [_response("end_turn", [_text_block("hi")])]
    )
    client = AsyncMock()
    client.messages.create = create

    with patch("app.agent.providers.anthropic_provider.anthropic.AsyncAnthropic", return_value=client):
        await core.run_turn([], "hi", model_id="claude-opus-4-8")

    system_prompt = call_snapshots[0]["system"]
    assert "lesson-doc" in system_prompt
    assert system_prompt.startswith(core.SYSTEM_PROMPT)


@pytest.mark.asyncio
async def test_run_turn_no_specs_uses_plain_system_prompt(db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    create, call_snapshots = _mock_create(
        [_response("end_turn", [_text_block("hi")])]
    )
    client = AsyncMock()
    client.messages.create = create

    with patch("app.agent.providers.anthropic_provider.anthropic.AsyncAnthropic", return_value=client):
        await core.run_turn([], "hi", model_id="claude-opus-4-8")

    assert call_snapshots[0]["system"] == core.SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_run_turn_does_not_surface_specs_on_nonempty_history(db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    workflow_specs.save_workflow_spec("lesson-doc", "spec content")

    create, call_snapshots = _mock_create(
        [_response("end_turn", [_text_block("hi")])]
    )
    client = AsyncMock()
    client.messages.create = create

    history = [
        {"role": "user", "content": "earlier message"},
        {"role": "assistant", "content": "earlier reply"},
    ]
    with patch("app.agent.providers.anthropic_provider.anthropic.AsyncAnthropic", return_value=client):
        await core.run_turn(history, "hi", model_id="claude-opus-4-8")

    assert call_snapshots[0]["system"] == core.SYSTEM_PROMPT
