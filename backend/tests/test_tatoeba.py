import pytest
import respx
from httpx import Response

from app.clients import tatoeba


@respx.mock
async def test_search_sentences_with_audio_and_translation():
    respx.get(tatoeba.API_BASE_URL).mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {
                        "id": 1,
                        "text": "猫が好きです。",
                        "lang": "jpn",
                        "translations": [{"id": 2, "text": "I like cats.", "lang": "eng"}],
                        "audios": [
                            {
                                "id": 99,
                                "author": "kevin62",
                                "download_url": "https://example.com/audio/99.mp3",
                            }
                        ],
                    }
                ],
                "paging": {"total": 1, "has_next": False},
            },
        )
    )
    respx.get("https://example.com/audio/99.mp3").mock(
        return_value=Response(200, content=b"audio-bytes")
    )

    results = await tatoeba.search_sentences("猫", n=5)

    assert results == [
        {
            "japanese": "猫が好きです。",
            "english": "I like cats.",
            "audio": b"audio-bytes",
            "audio_author": "kevin62",
        }
    ]


@respx.mock
async def test_search_sentences_without_audio():
    respx.get(tatoeba.API_BASE_URL).mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {
                        "id": 1,
                        "text": "猫が好きです。",
                        "lang": "jpn",
                        "translations": [{"id": 2, "text": "I like cats.", "lang": "eng"}],
                        "audios": [],
                    }
                ],
                "paging": {"total": 1, "has_next": False},
            },
        )
    )

    results = await tatoeba.search_sentences("猫")

    assert results == [
        {
            "japanese": "猫が好きです。",
            "english": "I like cats.",
            "audio": None,
            "audio_author": None,
        }
    ]


@respx.mock
async def test_search_sentences_no_results():
    respx.get(tatoeba.API_BASE_URL).mock(
        return_value=Response(200, json={"data": [], "paging": {"total": 0, "has_next": False}})
    )

    results = await tatoeba.search_sentences("asdfqwerzxcv nonsense query")

    assert results == []


@respx.mock
async def test_search_sentences_raises_on_http_error():
    respx.get(tatoeba.API_BASE_URL).mock(
        return_value=Response(
            500,
            json={"message": "Error from search engine", "code": 500},
        )
    )

    with pytest.raises(tatoeba.TatoebaError, match="500"):
        await tatoeba.search_sentences("猫")


@respx.mock
async def test_search_sentences_raises_when_audio_download_fails():
    respx.get(tatoeba.API_BASE_URL).mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {
                        "id": 1,
                        "text": "猫が好きです。",
                        "translations": [{"id": 2, "text": "I like cats.", "lang": "eng"}],
                        "audios": [
                            {
                                "id": 99,
                                "author": "kevin62",
                                "download_url": "https://example.com/audio/missing.mp3",
                            }
                        ],
                    }
                ],
                "paging": {"total": 1, "has_next": False},
            },
        )
    )
    respx.get("https://example.com/audio/missing.mp3").mock(return_value=Response(404))

    with pytest.raises(tatoeba.TatoebaError, match="missing.mp3"):
        await tatoeba.search_sentences("猫")


@respx.mock
async def test_search_sentences_request_params():
    route = respx.get(tatoeba.API_BASE_URL).mock(
        return_value=Response(200, json={"data": [], "paging": {"total": 0, "has_next": False}})
    )

    await tatoeba.search_sentences("猫", n=2)

    request = route.calls[0].request
    assert request.url.params["lang"] == "jpn"
    assert request.url.params["q"] == "猫"
    assert request.url.params["trans:lang"] == "eng"
    assert request.url.params["sort"] == "relevance"
    assert request.url.params["limit"] == "2"
