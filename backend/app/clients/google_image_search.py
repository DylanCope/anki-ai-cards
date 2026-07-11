"""Async client for Google Custom Search's image search (JSON API).

Finds candidate images for a query so Dylan can pick the best one for a
card, mirroring `elevenlabs.generate_audio_options`'s "return several raw
options" shape — the caller (the `search_images` tool in `app/agent/tools.py`)
is responsible for persisting the returned bytes and handing back stable ids,
not this module.

Requires a Google Programmable Search Engine configured for image search
(`GOOGLE_CSE_ID`) — a one-time manual setup step in Google's console, not
something this client can do; see PRD.md's Requirements section.
"""

import os

import httpx

API_BASE_URL = "https://www.googleapis.com/customsearch/v1"


class GoogleImageSearchError(Exception):
    """Raised when the Custom Search API, or an individual image download,
    returns a non-2xx response."""


def _api_key() -> str:
    return os.environ["GOOGLE_CSE_API_KEY"]


def _cse_id() -> str:
    return os.environ["GOOGLE_CSE_ID"]


async def search_images(query: str, n: int = 3) -> list[bytes]:
    """Search Google Images for `query`, downloading up to `n` results and
    returning their raw image bytes. Returns an empty list if the search
    finds no results."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            API_BASE_URL,
            params={
                "key": _api_key(),
                "cx": _cse_id(),
                "q": query,
                "searchType": "image",
                "num": n,
            },
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                api_detail = response.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                api_detail = response.text
            raise GoogleImageSearchError(
                f"Google Custom Search API error ({response.status_code}): {api_detail}"
            ) from exc

        items = response.json().get("items", [])

        results = []
        for item in items:
            image_url = item["link"]
            try:
                image_response = await client.get(image_url)
                image_response.raise_for_status()
            except httpx.HTTPError as exc:
                raise GoogleImageSearchError(
                    f"Failed to download image from {image_url}: {exc}"
                ) from exc
            results.append(image_response.content)

    return results
