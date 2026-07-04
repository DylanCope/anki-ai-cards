import json

import pytest
import respx
from httpx import Response

from app.clients import elevenlabs

API_KEY = "test-api-key"


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", API_KEY)


@respx.mock
async def test_generate_audio_options_makes_three_distinct_requests():
    route = respx.post(
        f"{elevenlabs.API_BASE_URL}/text-to-speech/{elevenlabs.DEFAULT_VOICE_ID}"
    ).mock(
        side_effect=[
            Response(200, content=b"audio-one"),
            Response(200, content=b"audio-two"),
            Response(200, content=b"audio-three"),
        ]
    )

    results = await elevenlabs.generate_audio_options("食べる", n=3)

    assert results == [b"audio-one", b"audio-two", b"audio-three"]
    assert route.call_count == 3

    bodies = [json.loads(call.request.content) for call in route.calls]
    assert all(body["text"] == "食べる" for body in bodies)
    assert all(body["model_id"] == elevenlabs.MODEL_ID for body in bodies)
    # Each request should use different voice settings so the outputs vary.
    voice_settings = [body["voice_settings"] for body in bodies]
    assert len({json.dumps(v, sort_keys=True) for v in voice_settings}) == 3

    for call in route.calls:
        assert call.request.headers["xi-api-key"] == API_KEY


@respx.mock
async def test_generate_audio_options_respects_n():
    respx.post(
        f"{elevenlabs.API_BASE_URL}/text-to-speech/{elevenlabs.DEFAULT_VOICE_ID}"
    ).mock(return_value=Response(200, content=b"audio"))

    results = await elevenlabs.generate_audio_options("hello", n=1)

    assert results == [b"audio"]


@respx.mock
async def test_generate_audio_options_raises_elevenlabs_error_with_api_detail():
    respx.post(
        f"{elevenlabs.API_BASE_URL}/text-to-speech/{elevenlabs.DEFAULT_VOICE_ID}"
    ).mock(
        return_value=Response(
            402,
            json={
                "detail": {
                    "type": "payment_required",
                    "code": "paid_plan_required",
                    "message": (
                        "Free users cannot use library voices via the API. "
                        "Please upgrade your subscription to use this voice."
                    ),
                    "status": "payment_required",
                }
            },
        )
    )

    with pytest.raises(elevenlabs.ElevenLabsError, match="library voices"):
        await elevenlabs.generate_audio_options("hello", n=1)


@respx.mock
async def test_generate_audio_options_raises_elevenlabs_error_for_non_json_body():
    respx.post(
        f"{elevenlabs.API_BASE_URL}/text-to-speech/{elevenlabs.DEFAULT_VOICE_ID}"
    ).mock(return_value=Response(500, text="internal server error"))

    with pytest.raises(elevenlabs.ElevenLabsError, match="internal server error"):
        await elevenlabs.generate_audio_options("hello", n=1)
