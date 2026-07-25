import pytest
import respx
from httpx import Response

from app.clients import azure_tts

API_KEY = "test-azure-key"
REGION = "japaneast"


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    monkeypatch.setenv("AZURE_SPEECH_KEY", API_KEY)
    monkeypatch.setenv("AZURE_SPEECH_REGION", REGION)


def _url() -> str:
    return azure_tts.API_BASE_URL_TEMPLATE.format(region=REGION)


@respx.mock
async def test_generate_audio_options_makes_three_distinct_requests():
    route = respx.post(_url()).mock(
        side_effect=[
            Response(200, content=b"audio-one"),
            Response(200, content=b"audio-two"),
            Response(200, content=b"audio-three"),
        ]
    )

    results = await azure_tts.generate_audio_options("食べる", n=3)

    assert results == [b"audio-one", b"audio-two", b"audio-three"]
    assert route.call_count == 3

    bodies = [call.request.content.decode("utf-8") for call in route.calls]
    assert all("食べる" in body for body in bodies)
    assert all(azure_tts.VOICE_IDS[azure_tts.DEFAULT_VOICE] in body for body in bodies)
    # Each request should use a different prosody so the outputs vary.
    assert len(set(bodies)) == 3

    for call in route.calls:
        assert call.request.headers["Ocp-Apim-Subscription-Key"] == API_KEY


@respx.mock
async def test_generate_audio_options_respects_n():
    respx.post(_url()).mock(return_value=Response(200, content=b"audio"))

    results = await azure_tts.generate_audio_options("hello", n=1)

    assert results == [b"audio"]


@respx.mock
async def test_generate_audio_options_raises_azure_tts_error_for_error_response():
    respx.post(_url()).mock(return_value=Response(401, text="Access denied"))

    with pytest.raises(azure_tts.AzureTTSError, match="Access denied"):
        await azure_tts.generate_audio_options("hello", n=1)


@respx.mock
async def test_generate_audio_options_uses_female_voice_id():
    route = respx.post(_url()).mock(return_value=Response(200, content=b"audio"))

    results = await azure_tts.generate_audio_options("hello", n=1, voice="female")

    assert results == [b"audio"]
    body = route.calls[0].request.content.decode("utf-8")
    assert azure_tts.VOICE_IDS["female"] in body


async def test_generate_audio_options_rejects_unknown_voice():
    with pytest.raises(ValueError, match="Unknown voice"):
        await azure_tts.generate_audio_options("hello", n=1, voice="robot")


@respx.mock
async def test_generate_audio_options_substitutes_reading_from_segments():
    route = respx.post(_url()).mock(return_value=Response(200, content=b"audio"))

    await azure_tts.generate_audio_options(
        "明日行きます",
        n=1,
        segments=[{"text": "明日", "reading": "あした"}, {"text": "行きます"}],
    )

    body = route.calls[0].request.content.decode("utf-8")
    assert "あした" in body
    assert "行きます" in body
    assert "明日" not in body
