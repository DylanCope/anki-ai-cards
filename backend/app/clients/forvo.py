"""Async client for Forvo's word-pronunciations API.

Finds real, native speaker pronunciations for a Japanese word so a card's
audio doesn't have to rely solely on ElevenLabs TTS, mirroring
`wikimedia_image_search.search_images`'s "return several raw options, let the
caller persist/attach them" shape — the caller (the
`search_word_pronunciations` tool in `app/agent/tools.py`) is responsible for
storing the returned audio as an `AudioClip` and handing back stable ids, not
this module.

Confirmed against Forvo's actual documented API (https://api.forvo.com/
documentation/word-pronunciations/, and the field names used by several
independent third-party API wrapper libraries that parse real responses,
e.g. https://github.com/ryanj1234/pyforvo/blob/master/pyforvo/forvo.py, since
Forvo's own docs page shows example *request* URLs but not a full JSON
response body): requests are path-based (not query-string) —
`GET https://apifree.forvo.com/key/{key}/format/json/action/
word-pronunciations/word/{word}/language/{lang}/order/{order}/limit/{n}` —
and each item in the response's `items` array has (among other fields)
`username`, `pathmp3`, `num_votes`, and `rate`. `order=rate-desc` sorts by
Forvo's vote/rating count, highest first, which is what this client asks for.

Per Forvo's own "General Information" documentation
(https://api.forvo.com/documentation/general-information/), a `pathmp3` URL
is only valid for 2 hours after the API call that returned it — this client
downloads immediately rather than returning the URL itself, so that window
never matters to the caller.
"""

import os
from urllib.parse import quote

import httpx

API_BASE_URL = "https://apifree.forvo.com"


class ForvoError(Exception):
    """Raised when the Forvo API, or an individual audio download, returns a
    non-2xx response or an API-level error."""


def _api_key() -> str:
    return os.environ["FORVO_API_KEY"]


async def search_pronunciations(word: str, n: int = 3) -> list[dict]:
    """Search Forvo for Japanese pronunciations of `word`, downloading the
    top `n` (by vote/rating count, highest first) and returning their raw
    audio bytes.

    Returns up to `n` dicts shaped `{"audio": bytes, "username": str | None}`
    — `username` is the Forvo speaker who recorded that pronunciation, when
    Forvo reports one. Returns an empty list if Forvo has no pronunciations
    for the word."""
    url = (
        f"{API_BASE_URL}/key/{quote(_api_key(), safe='')}/format/json/action/"
        f"word-pronunciations/word/{quote(word, safe='')}/language/ja/"
        f"order/rate-desc/limit/{n}"
    )
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ForvoError(
                f"Forvo API error ({response.status_code}): {response.text}"
            ) from exc

        payload = response.json()
        if isinstance(payload, dict) and "error" in payload:
            raise ForvoError(f"Forvo API error: {payload['error']}")

        items = payload.get("items", []) if isinstance(payload, dict) else []

        results = []
        for item in items:
            download_url = item["pathmp3"]
            try:
                audio_response = await client.get(download_url)
                audio_response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ForvoError(
                    f"Failed to download Forvo audio from {download_url}: {exc}"
                ) from exc
            results.append(
                {"audio": audio_response.content, "username": item.get("username")}
            )

        return results
