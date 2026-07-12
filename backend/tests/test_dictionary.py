import pytest
import respx
from httpx import Response

from app.clients import dictionary


@respx.mock
async def test_search_words_multi_result_query():
    respx.get(dictionary.API_URL).mock(
        return_value=Response(
            200,
            json={
                "meta": {"status": 200},
                "data": [
                    {
                        "slug": "猫",
                        "is_common": True,
                        "japanese": [
                            {"word": "猫", "reading": "ねこ"},
                            {"reading": "ネコ"},
                        ],
                        "senses": [
                            {
                                "english_definitions": [
                                    "cat (esp. the domestic cat, Felis catus)",
                                    "feline",
                                ],
                                "parts_of_speech": ["Noun"],
                            },
                            {
                                "english_definitions": ["shamisen"],
                                "parts_of_speech": ["Noun"],
                            },
                        ],
                    },
                    {
                        "slug": "猫背",
                        "is_common": True,
                        "japanese": [{"word": "猫背", "reading": "ねこぜ"}],
                        "senses": [
                            {
                                "english_definitions": ["bent back", "hunchback", "stoop"],
                                "parts_of_speech": [
                                    "Noun",
                                    "Na-adjective (keiyodoshi)",
                                ],
                            }
                        ],
                    },
                ],
            },
        )
    )

    results = await dictionary.search_words("猫", n=2)

    assert len(results) == 2

    cat = results[0]
    assert cat["word"] == "猫"
    assert cat["readings"] == ["ねこ", "ネコ"]
    assert cat["meanings"] == [
        "cat (esp. the domestic cat, Felis catus)",
        "feline",
        "shamisen",
    ]
    assert cat["parts_of_speech"] == ["Noun"]
    assert cat["is_common"] is True
    assert cat["frequency"] > 0

    hunchback = results[1]
    assert hunchback["word"] == "猫背"
    assert hunchback["readings"] == ["ねこぜ"]
    assert sorted(hunchback["parts_of_speech"]) == ["Na-adjective (keiyodoshi)", "Noun"]


@respx.mock
async def test_search_words_respects_n():
    respx.get(dictionary.API_URL).mock(
        return_value=Response(
            200,
            json={
                "meta": {"status": 200},
                "data": [
                    {
                        "slug": "猫",
                        "is_common": True,
                        "japanese": [{"word": "猫", "reading": "ねこ"}],
                        "senses": [
                            {"english_definitions": ["cat"], "parts_of_speech": ["Noun"]}
                        ],
                    },
                    {
                        "slug": "猫背",
                        "is_common": True,
                        "japanese": [{"word": "猫背", "reading": "ねこぜ"}],
                        "senses": [
                            {
                                "english_definitions": ["hunchback"],
                                "parts_of_speech": ["Noun"],
                            }
                        ],
                    },
                ],
            },
        )
    )

    results = await dictionary.search_words("猫", n=1)

    assert len(results) == 1
    assert results[0]["word"] == "猫"


@respx.mock
async def test_search_words_no_results():
    respx.get(dictionary.API_URL).mock(
        return_value=Response(200, json={"meta": {"status": 200}, "data": []})
    )

    results = await dictionary.search_words("asdfqwerzxcv nonsense query")

    assert results == []


@respx.mock
async def test_search_words_falls_back_to_reading_when_no_kanji_form():
    respx.get(dictionary.API_URL).mock(
        return_value=Response(
            200,
            json={
                "meta": {"status": 200},
                "data": [
                    {
                        "slug": "です",
                        "is_common": True,
                        "japanese": [{"reading": "です"}],
                        "senses": [
                            {
                                "english_definitions": ["to be", "is"],
                                "parts_of_speech": ["Auxiliary verb"],
                            }
                        ],
                    }
                ],
            },
        )
    )

    results = await dictionary.search_words("です")

    assert results[0]["word"] == "です"
    assert results[0]["readings"] == ["です"]


@respx.mock
async def test_search_words_raises_on_http_error():
    respx.get(dictionary.API_URL).mock(
        return_value=Response(500, text="Internal Server Error")
    )

    with pytest.raises(dictionary.DictionaryError, match="500"):
        await dictionary.search_words("猫")


@respx.mock
async def test_search_words_request_params():
    route = respx.get(dictionary.API_URL).mock(
        return_value=Response(200, json={"meta": {"status": 200}, "data": []})
    )

    await dictionary.search_words("猫")

    request = route.calls[0].request
    assert request.url.params["keyword"] == "猫"
