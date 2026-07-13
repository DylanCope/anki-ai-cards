from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import types
from google.genai import errors as genai_errors

from app.clients import gemini_images


def _image_response(data: bytes, mime_type: str = "image/png"):
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            inline_data=types.Blob(data=data, mime_type=mime_type)
                        )
                    ],
                )
            )
        ],
    )


def _patch_client(monkeypatch, generate_content):
    fake_client = MagicMock()
    fake_client.aio.models.generate_content = generate_content
    monkeypatch.setattr(gemini_images.genai, "Client", MagicMock(return_value=fake_client))


@pytest.mark.asyncio
async def test_generate_images_calls_gemini_n_times_and_returns_bytes(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    responses = [_image_response(b"image-1"), _image_response(b"image-2"), _image_response(b"image-3")]
    generate_content = AsyncMock(side_effect=responses)
    _patch_client(monkeypatch, generate_content)

    results = await gemini_images.generate_images("a shiba inu", n=3)

    assert results == [b"image-1", b"image-2", b"image-3"]
    assert generate_content.await_count == 3
    call_kwargs = generate_content.call_args.kwargs
    assert call_kwargs["model"] == gemini_images.MODEL_ID
    assert call_kwargs["contents"] == "a shiba inu"
    assert call_kwargs["config"].response_modalities == [types.Modality.IMAGE]


@pytest.mark.asyncio
async def test_generate_images_respects_custom_n(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    generate_content = AsyncMock(return_value=_image_response(b"image-1"))
    _patch_client(monkeypatch, generate_content)

    results = await gemini_images.generate_images("a shiba inu", n=1)

    assert results == [b"image-1"]
    assert generate_content.await_count == 1


@pytest.mark.asyncio
async def test_generate_images_raises_on_api_error(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    error = genai_errors.ClientError(
        429, {"error": {"message": "quota exceeded"}}
    )
    generate_content = AsyncMock(side_effect=error)
    _patch_client(monkeypatch, generate_content)

    with pytest.raises(gemini_images.GeminiImageError, match="quota exceeded"):
        await gemini_images.generate_images("a shiba inu")


@pytest.mark.asyncio
async def test_generate_images_raises_when_response_has_no_image(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    empty_response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(content=types.Content(role="model", parts=[types.Part.from_text(text="sorry")]))
        ],
    )
    generate_content = AsyncMock(return_value=empty_response)
    _patch_client(monkeypatch, generate_content)

    with pytest.raises(gemini_images.GeminiImageError, match="no image data"):
        await gemini_images.generate_images("a shiba inu")
