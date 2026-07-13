import pytest
import respx
from httpx import Response

from app.clients import wikimedia_image_search


@respx.mock
async def test_search_images_downloads_each_result():
    search_route = respx.get(wikimedia_image_search.API_BASE_URL).mock(
        return_value=Response(
            200,
            json={
                "query": {
                    "pages": {
                        "111": {
                            "title": "File:Shiba one.jpg",
                            "imageinfo": [
                                {
                                    "url": "https://example.com/one-original.jpg",
                                    "thumburl": "https://example.com/one.jpg",
                                }
                            ],
                        },
                        "222": {
                            "title": "File:Shiba two.jpg",
                            "imageinfo": [{"url": "https://example.com/two.jpg"}],
                        },
                        "333": {
                            "title": "File:Shiba three.jpg",
                            "imageinfo": [{"url": "https://example.com/three.jpg"}],
                        },
                    }
                }
            },
        )
    )
    respx.get("https://example.com/one.jpg").mock(return_value=Response(200, content=b"image-one"))
    respx.get("https://example.com/two.jpg").mock(return_value=Response(200, content=b"image-two"))
    respx.get("https://example.com/three.jpg").mock(return_value=Response(200, content=b"image-three"))

    results = await wikimedia_image_search.search_images("shiba inu", n=3)

    assert results == [b"image-one", b"image-two", b"image-three"]
    assert search_route.call_count == 1
    request = search_route.calls[0].request
    assert request.url.params["generator"] == "search"
    assert request.url.params["gsrsearch"] == "filetype:bitmap|drawing shiba inu"
    assert request.url.params["gsrnamespace"] == "6"
    assert request.url.params["gsrlimit"] == "3"
    assert request.url.params["iiurlwidth"] == "800"
    assert request.headers["User-Agent"] == wikimedia_image_search.USER_AGENT


@respx.mock
async def test_search_images_returns_empty_list_when_no_results():
    respx.get(wikimedia_image_search.API_BASE_URL).mock(
        return_value=Response(200, json={"batchcomplete": ""})
    )

    results = await wikimedia_image_search.search_images("asdfqwerzxcv nonsense query")

    assert results == []


@respx.mock
async def test_search_images_raises_on_http_error():
    respx.get(wikimedia_image_search.API_BASE_URL).mock(return_value=Response(500))

    with pytest.raises(wikimedia_image_search.WikimediaImageSearchError, match="500"):
        await wikimedia_image_search.search_images("shiba inu")


@respx.mock
async def test_search_images_raises_on_api_error():
    respx.get(wikimedia_image_search.API_BASE_URL).mock(
        return_value=Response(
            200,
            json={"error": {"code": "badsearchtype", "info": "Bad search syntax"}},
        )
    )

    with pytest.raises(wikimedia_image_search.WikimediaImageSearchError, match="Bad search syntax"):
        await wikimedia_image_search.search_images("shiba inu")


@respx.mock
async def test_search_images_raises_when_image_download_fails():
    respx.get(wikimedia_image_search.API_BASE_URL).mock(
        return_value=Response(
            200,
            json={
                "query": {
                    "pages": {
                        "111": {
                            "title": "File:Missing.jpg",
                            "imageinfo": [{"url": "https://example.com/missing.jpg"}],
                        }
                    }
                }
            },
        )
    )
    respx.get("https://example.com/missing.jpg").mock(return_value=Response(404))

    with pytest.raises(wikimedia_image_search.WikimediaImageSearchError, match="missing.jpg"):
        await wikimedia_image_search.search_images("shiba inu")
