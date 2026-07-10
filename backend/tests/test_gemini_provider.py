from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import types

from app.agent.providers import gemini_provider


def _make_response(parts: list[types.Part], *, model_version: str = "gemini-2.5-flash"):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=parts))],
        model_version=model_version,
    )


def test_to_gemini_contents_translates_plain_text_turns():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]

    contents = gemini_provider._to_gemini_contents(messages)

    assert [c.role for c in contents] == ["user", "model"]
    assert contents[0].parts[0].text == "hello"
    assert contents[1].parts[0].text == "hi there"


def test_to_gemini_contents_translates_tool_use_and_tool_result():
    messages = [
        {"role": "user", "content": "what note types do I have?"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "call-1", "name": "list_anki_note_types", "input": {}}
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": '["Basic", "Cloze"]'}
            ],
        },
    ]

    contents = gemini_provider._to_gemini_contents(messages)

    tool_use_part = contents[1].parts[0]
    assert tool_use_part.function_call.name == "list_anki_note_types"
    assert tool_use_part.function_call.id == "call-1"

    tool_result_part = contents[2].parts[0]
    assert tool_result_part.function_response.name == "list_anki_note_types"
    assert tool_result_part.function_response.id == "call-1"
    assert tool_result_part.function_response.response == {"result": ["Basic", "Cloze"]}


def test_to_gemini_contents_wraps_error_tool_result_under_error_key():
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "call-1", "name": "sync_anki", "input": {}}],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call-1",
                    "content": "sync_anki failed: timed out",
                    "is_error": True,
                }
            ],
        },
    ]

    contents = gemini_provider._to_gemini_contents(messages)

    response_payload = contents[2].parts[0].function_response.response
    assert response_payload == {"error": "sync_anki failed: timed out"}


def test_to_internal_response_text_only_is_end_turn():
    response = _make_response([types.Part.from_text(text="Here you go.")])

    result = gemini_provider._to_internal_response(response)

    assert result.stop_reason == "end_turn"
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert result.content[0].text == "Here you go."


def test_to_internal_response_function_call_is_tool_use():
    response = _make_response(
        [
            types.Part.from_text(text="Let me check."),
            types.Part(
                function_call=types.FunctionCall(
                    id="call-42", name="list_anki_note_types", args={}
                )
            ),
        ]
    )

    result = gemini_provider._to_internal_response(response)

    assert result.stop_reason == "tool_use"
    text_block, tool_block = result.content
    assert text_block.type == "text"
    assert tool_block.type == "tool_use"
    assert tool_block.id == "call-42"
    assert tool_block.name == "list_anki_note_types"
    assert tool_block.input == {}


def test_to_internal_response_synthesizes_id_when_gemini_omits_one():
    response = _make_response(
        [types.Part(function_call=types.FunctionCall(name="sync_anki", args={}))]
    )

    result = gemini_provider._to_internal_response(response)

    assert result.content[0].id.startswith("gemini_call_")


@pytest.mark.asyncio
async def test_create_message_calls_gemini_and_returns_normalized_response(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    canned_response = _make_response([types.Part.from_text(text="Cloze and Basic.")])
    generate_content = AsyncMock(return_value=canned_response)
    fake_client = MagicMock()
    fake_client.aio.models.generate_content = generate_content
    monkeypatch.setattr(gemini_provider.genai, "Client", MagicMock(return_value=fake_client))

    result = await gemini_provider.create_message(
        system="You are a helpful assistant.",
        tools=[
            {
                "name": "list_anki_note_types",
                "description": "List note types.",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
        messages=[{"role": "user", "content": "what note types do I have?"}],
        max_tokens=4096,
        model_id="gemini-2.5-flash",
    )

    assert result.stop_reason == "end_turn"
    assert result.content[0].text == "Cloze and Basic."

    generate_content.assert_awaited_once()
    call_kwargs = generate_content.call_args.kwargs
    assert call_kwargs["model"] == "gemini-2.5-flash"
    config = call_kwargs["config"]
    assert config.system_instruction == "You are a helpful assistant."
    assert config.tools[0].function_declarations[0].name == "list_anki_note_types"
    assert config.automatic_function_calling.disable is True
