import pytest
import respx
from httpx import Response

from app.clients import forvo


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("FORVO_API_KEY", "test-key")


@respx.mock
async def test_search_pronunciations_returns_audio_and_username():
    respx.get(url__regex=r"https://apifree\.forvo\.com/key/test-key/.*").mock(
        return_value=Response(
            200,
            json={
                "attributes": {"total": 1},
                "items": [
                    {
                        "id": 5943,
                        "word": "猫",
                        "username": "kevin62",
                        "pathmp3": "https://example.com/audio/5943.mp3",
                        "num_votes": 10,
                        "rate": 8,
                    }
                ],
            },
        )
    )
    respx.get("https://example.com/audio/5943.mp3").mock(
        return_value=Response(200, content=b"audio-bytes")
    )

    results = await forvo.search_pronunciations("猫", n=3)

    assert results == [{"audio": b"audio-bytes", "username": "kevin62"}]


@respx.mock
async def test_search_pronunciations_no_username_falls_back_to_none():
    respx.get(url__regex=r"https://apifree\.forvo\.com/key/test-key/.*").mock(
        return_value=Response(
            200,
            json={
                "attributes": {"total": 1},
                "items": [
                    {
                        "id": 1,
                        "word": "猫",
                        "pathmp3": "https://example.com/audio/1.mp3",
                    }
                ],
            },
        )
    )
    respx.get("https://example.com/audio/1.mp3").mock(
        return_value=Response(200, content=b"audio-bytes")
    )

    results = await forvo.search_pronunciations("猫")

    assert results == [{"audio": b"audio-bytes", "username": None}]


@respx.mock
async def test_search_pronunciations_no_results():
    respx.get(url__regex=r"https://apifree\.forvo\.com/key/test-key/.*").mock(
        return_value=Response(200, json={"attributes": {"total": 0}, "items": []})
    )

    results = await forvo.search_pronunciations("asdfqwerzxcv nonsense query")

    assert results == []


@respx.mock
async def test_search_pronunciations_raises_on_http_error():
    respx.get(url__regex=r"https://apifree\.forvo\.com/key/test-key/.*").mock(
        return_value=Response(500, text="Internal Server Error")
    )

    with pytest.raises(forvo.ForvoError, match="500"):
        await forvo.search_pronunciations("猫")


@respx.mock
async def test_search_pronunciations_raises_on_api_error():
    respx.get(url__regex=r"https://apifree\.forvo\.com/key/test-key/.*").mock(
        return_value=Response(200, json={"error": "Invalid API Key."})
    )

    with pytest.raises(forvo.ForvoError, match="Invalid API Key"):
        await forvo.search_pronunciations("猫")


@respx.mock
async def test_search_pronunciations_raises_when_audio_download_fails():
    respx.get(url__regex=r"https://apifree\.forvo\.com/key/test-key/.*").mock(
        return_value=Response(
            200,
            json={
                "attributes": {"total": 1},
                "items": [
                    {
                        "id": 1,
                        "word": "猫",
                        "username": "kevin62",
                        "pathmp3": "https://example.com/audio/missing.mp3",
                    }
                ],
            },
        )
    )
    respx.get("https://example.com/audio/missing.mp3").mock(return_value=Response(404))

    with pytest.raises(forvo.ForvoError, match="missing.mp3"):
        await forvo.search_pronunciations("猫")


@respx.mock
async def test_search_pronunciations_request_url():
    route = respx.get(url__regex=r"https://apifree\.forvo\.com/key/test-key/.*").mock(
        return_value=Response(200, json={"attributes": {"total": 0}, "items": []})
    )

    await forvo.search_pronunciations("猫", n=2)

    request = route.calls[0].request
    url = str(request.url)
    assert url.startswith("https://apifree.forvo.com/key/test-key/format/json/action/word-pronunciations/word/")
    assert "language/ja" in url
    assert "order/rate-desc" in url
    assert "limit/2" in url
