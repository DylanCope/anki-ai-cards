import base64
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
async def test_dispatch_generate_audio(monkeypatch):
    mock = AsyncMock(return_value=[b"aaa", b"bbb", b"ccc"])
    monkeypatch.setattr(tools.elevenlabs, "generate_audio_options", mock)

    result = await tools.dispatch_tool("generate_audio", {"text": "こんにちは"})

    mock.assert_awaited_once_with("こんにちは", n=3, voice=tools.elevenlabs.DEFAULT_VOICE)
    assert result == [base64.b64encode(b).decode("ascii") for b in [b"aaa", b"bbb", b"ccc"]]


@pytest.mark.asyncio
async def test_dispatch_generate_audio_custom_n(monkeypatch):
    mock = AsyncMock(return_value=[b"aaa"])
    monkeypatch.setattr(tools.elevenlabs, "generate_audio_options", mock)

    await tools.dispatch_tool("generate_audio", {"text": "hi", "n": 1})

    mock.assert_awaited_once_with("hi", n=1, voice=tools.elevenlabs.DEFAULT_VOICE)


@pytest.mark.asyncio
async def test_dispatch_generate_audio_custom_voice(monkeypatch):
    mock = AsyncMock(return_value=[b"aaa"])
    monkeypatch.setattr(tools.elevenlabs, "generate_audio_options", mock)

    await tools.dispatch_tool("generate_audio", {"text": "hi", "voice": "female"})

    mock.assert_awaited_once_with("hi", n=3, voice="female")


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
    )
    assert result == {"note_id": 12345}


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

    with patch("app.agent.core.anthropic.AsyncAnthropic", return_value=client):
        result = await core.run_turn([], "hi")

    assert result["reply"] == "Hello Dylan!"
    assert len(call_snapshots) == 1
    kwargs = call_snapshots[0]
    assert kwargs["model"] == core.MODEL_ID
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

    with patch("app.agent.core.anthropic.AsyncAnthropic", return_value=client):
        result = await core.run_turn([], "what note types do I have?")

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

    with patch("app.agent.core.anthropic.AsyncAnthropic", return_value=client):
        await core.run_turn([], "read the doc", access_token="tok-xyz")

    fetch_mock.assert_awaited_once_with("abc", "tok-xyz")


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

    with patch("app.agent.core.anthropic.AsyncAnthropic", return_value=client):
        await core.run_turn([], "hi")

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

    with patch("app.agent.core.anthropic.AsyncAnthropic", return_value=client):
        await core.run_turn([], "hi")

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
    with patch("app.agent.core.anthropic.AsyncAnthropic", return_value=client):
        await core.run_turn(history, "hi")

    assert call_snapshots[0]["system"] == core.SYSTEM_PROMPT
