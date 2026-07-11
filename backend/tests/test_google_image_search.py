import pytest
import respx
from httpx import Response

from app.clients import google_image_search

API_KEY = "test-cse-key"
CSE_ID = "test-cse-id"


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CSE_API_KEY", API_KEY)
    monkeypatch.setenv("GOOGLE_CSE_ID", CSE_ID)


@respx.mock
async def test_search_images_downloads_each_result():
    search_route = respx.get(google_image_search.API_BASE_URL).mock(
        return_value=Response(
            200,
            json={
                "items": [
                    {"link": "https://example.com/one.jpg"},
                    {"link": "https://example.com/two.jpg"},
                    {"link": "https://example.com/three.jpg"},
                ]
            },
        )
    )
    respx.get("https://example.com/one.jpg").mock(return_value=Response(200, content=b"image-one"))
    respx.get("https://example.com/two.jpg").mock(return_value=Response(200, content=b"image-two"))
    respx.get("https://example.com/three.jpg").mock(return_value=Response(200, content=b"image-three"))

    results = await google_image_search.search_images("shiba inu", n=3)

    assert results == [b"image-one", b"image-two", b"image-three"]
    assert search_route.call_count == 1
    request = search_route.calls[0].request
    assert request.url.params["key"] == API_KEY
    assert request.url.params["cx"] == CSE_ID
    assert request.url.params["q"] == "shiba inu"
    assert request.url.params["searchType"] == "image"
    assert request.url.params["num"] == "3"


@respx.mock
async def test_search_images_returns_empty_list_when_no_results():
    respx.get(google_image_search.API_BASE_URL).mock(
        return_value=Response(200, json={"searchInformation": {"totalResults": "0"}})
    )

    results = await google_image_search.search_images("asdfqwerzxcv nonsense query")

    assert results == []


@respx.mock
async def test_search_images_raises_on_api_error():
    respx.get(google_image_search.API_BASE_URL).mock(
        return_value=Response(
            403,
            json={"error": {"code": 403, "message": "Daily Limit Exceeded"}},
        )
    )

    with pytest.raises(google_image_search.GoogleImageSearchError, match="Daily Limit Exceeded"):
        await google_image_search.search_images("shiba inu")


@respx.mock
async def test_search_images_raises_when_image_download_fails():
    respx.get(google_image_search.API_BASE_URL).mock(
        return_value=Response(
            200, json={"items": [{"link": "https://example.com/missing.jpg"}]}
        )
    )
    respx.get("https://example.com/missing.jpg").mock(return_value=Response(404))

    with pytest.raises(google_image_search.GoogleImageSearchError, match="missing.jpg"):
        await google_image_search.search_images("shiba inu")
