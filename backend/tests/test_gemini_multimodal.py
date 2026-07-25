from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import errors as genai_errors
from google.genai import types

from app.clients import gemini_multimodal


def _text_response(text: str):
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part.from_text(text=text)])
            )
        ],
    )


def _patch_client(monkeypatch, generate_content):
    fake_client = MagicMock()
    fake_client.aio.models.generate_content = generate_content
    monkeypatch.setattr(gemini_multimodal.genai, "Client", MagicMock(return_value=fake_client))


@pytest.mark.asyncio
async def test_ask_sends_ordered_text_and_media_parts(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    generate_content = AsyncMock(return_value=_text_response("B sounds more natural"))
    _patch_client(monkeypatch, generate_content)

    parts = [
        {"text": "Option A:"},
        {"data": b"audio-a", "mime_type": "audio/mpeg"},
        {"text": "Option B:"},
        {"data": b"audio-b", "mime_type": "audio/mpeg"},
    ]
    result = await gemini_multimodal.ask(parts)

    assert result == "B sounds more natural"
    call_kwargs = generate_content.call_args.kwargs
    assert call_kwargs["model"] == gemini_multimodal.MODEL_ID
    contents = call_kwargs["contents"]
    assert contents[0] == "Option A:"
    assert contents[1].inline_data.data == b"audio-a"
    assert contents[1].inline_data.mime_type == "audio/mpeg"
    assert contents[2] == "Option B:"
    assert contents[3].inline_data.data == b"audio-b"


@pytest.mark.asyncio
async def test_ask_raises_on_api_error(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    error = genai_errors.ClientError(429, {"error": {"message": "quota exceeded"}})
    generate_content = AsyncMock(side_effect=error)
    _patch_client(monkeypatch, generate_content)

    with pytest.raises(gemini_multimodal.GeminiMultimodalError, match="quota exceeded"):
        await gemini_multimodal.ask([{"text": "hello"}])


@pytest.mark.asyncio
async def test_ask_raises_when_response_has_no_text(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    empty_response = types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[]))],
    )
    generate_content = AsyncMock(return_value=empty_response)
    _patch_client(monkeypatch, generate_content)

    with pytest.raises(gemini_multimodal.GeminiMultimodalError, match="no text"):
        await gemini_multimodal.ask([{"text": "hello"}])
