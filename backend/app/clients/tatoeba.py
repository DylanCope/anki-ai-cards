"""Async client for Tatoeba's public sentence search API (api.tatoeba.org).

Finds real, native-written example sentences for a query so a card's
example doesn't have to be invented by the model, mirroring
`wikimedia_image_search.search_images`'s "return real options, let the
caller persist/attach them" shape — the caller (the `search_example_sentences`
tool in `app/agent/tools.py`) is responsible for storing any downloaded audio
as an `AudioClip` and handing back a stable `audio_id`, not this module.

This is api.tatoeba.org's current REST API (`GET /v1/sentences`, documented
at https://api.tatoeba.org/openapi), not the older `tatoeba.org/en/api_v0/*`
endpoint — that one is explicitly marked "deprecated" on Tatoeba's own wiki
and, confirmed directly (2026-07-12), now 500s on every request regardless of
parameters. Also confirmed directly against the real, current API: as of
2026-07-12 `GET /v1/sentences` itself 500s with `"Error from search engine:
connection to localhost:9312 failed"` for *any* query (including one with no
`q` at all) — Tatoeba's own full-text search backend (Manticore/Sphinx)
appears to be down service-side, reproduced repeatedly ~20s apart. This is an
outage on Tatoeba's end, not a bug in this client or its request shape —
`GET /v1/sentences/{id}` (no search-engine dependency) returns a normal 200
in the meantime, which is how the request/response shape below was confirmed
against the real API's OpenAPI spec and schema, just not exercised through a
live successful search response body.
"""

import httpx

API_BASE_URL = "https://api.tatoeba.org/v1/sentences"


class TatoebaError(Exception):
    """Raised when the Tatoeba search API, or an individual audio download,
    returns a non-2xx response or an API-level error."""


async def search_sentences(query: str, n: int = 5) -> list[dict]:
    """Search Tatoeba for Japanese sentences matching `query` that have an
    English translation, downloading native audio when available.

    Returns up to `n` dicts shaped `{"japanese": str, "english": str | None,
    "audio": bytes | None, "audio_author": str | None}` — `audio`/
    `audio_author` are set only when Tatoeba has a native recording for that
    sentence. Returns an empty list if the search finds no results."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            API_BASE_URL,
            params={
                "lang": "jpn",
                "q": query,
                "trans:lang": "eng",
                "sort": "relevance",
                "limit": n,
            },
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise TatoebaError(
                f"Tatoeba search API error ({response.status_code}): {response.text}"
            ) from exc

        payload = response.json()

        results = []
        for sentence in payload.get("data", []):
            translations = sentence.get("translations", [])
            english = translations[0]["text"] if translations else None

            audio_bytes = None
            audio_author = None
            audios = sentence.get("audios", [])
            if audios:
                download_url = audios[0]["download_url"]
                audio_response = await client.get(download_url)
                try:
                    audio_response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise TatoebaError(
                        f"Failed to download Tatoeba audio from {download_url}: {exc}"
                    ) from exc
                audio_bytes = audio_response.content
                audio_author = audios[0].get("author")

            results.append(
                {
                    "japanese": sentence["text"],
                    "english": english,
                    "audio": audio_bytes,
                    "audio_author": audio_author,
                }
            )

        return results
