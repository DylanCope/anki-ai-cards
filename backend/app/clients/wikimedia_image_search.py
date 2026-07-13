"""Async client for Wikimedia Commons' image search (MediaWiki API).

Finds candidate images for a query so Dylan can pick the best one for a
card, mirroring `elevenlabs.generate_audio_options`'s "return several raw
options" shape — the caller (the `search_images` tool in `app/agent/tools.py`)
is responsible for persisting the returned bytes and handing back stable ids,
not this module.

Replaces the earlier Google Custom Search JSON API client: that API was
confirmed (2026-07-12, via `fly ssh console` against the deployed backend,
tested across two separate GCP projects and three separate API keys) to be
closed to new Google Cloud customers as of 2025 — every request 403s with
"This project does not have the access to Custom Search JSON API"
regardless of project/billing/enablement state — and is being fully retired
2027-01-01. See PRD.md's Requirements section.

No API key or quota is needed. Wikimedia's Commons search covers the
`*.wikipedia.org/*` slice of what the old Google Programmable Search Engine
indexed; Dylan chose not to replace the other four sites
(irasutoya/unsplash/pexels/pixabay) with paid per-site APIs.
"""

import httpx

API_BASE_URL = "https://commons.wikimedia.org/w/api.php"

# Wikimedia requires a descriptive User-Agent with contact info for API
# clients (https://meta.wikimedia.org/wiki/User-Agent_policy); generic/unset
# UAs get rate-limited or blocked.
USER_AGENT = "anki-ai-cards/1.0 (dylanr.cope@gmail.com)"


class WikimediaImageSearchError(Exception):
    """Raised when the Commons search API, or an individual image download,
    returns a non-2xx response or an API-level error."""


async def search_images(query: str, n: int = 3) -> list[bytes]:
    """Search Wikimedia Commons for `query`, downloading up to `n` results
    and returning their raw image bytes. Returns an empty list if the
    search finds no results."""
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        response = await client.get(
            API_BASE_URL,
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                # Restrict to raster/vector images (excludes audio/video/PDF
                # files, which also live in the File: namespace on Commons).
                "gsrsearch": f"filetype:bitmap|drawing {query}",
                "gsrnamespace": 6,  # File:
                "gsrlimit": n,
                "prop": "imageinfo",
                "iiprop": "url",
                # Commons originals can be huge (scans/TIFFs well over
                # 100MB); request a thumbnail sized for a flashcard image
                # instead of downloading the original.
                "iiurlwidth": 800,
            },
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise WikimediaImageSearchError(
                f"Wikimedia Commons search API error ({response.status_code}): {response.text}"
            ) from exc

        payload = response.json()
        if "error" in payload:
            raise WikimediaImageSearchError(
                f"Wikimedia Commons search API error: {payload['error']}"
            )

        pages = payload.get("query", {}).get("pages", {})
        image_urls = [
            page["imageinfo"][0].get("thumburl") or page["imageinfo"][0]["url"]
            for page in pages.values()
            if page.get("imageinfo")
        ]

        results = []
        for image_url in image_urls:
            try:
                image_response = await client.get(image_url)
                image_response.raise_for_status()
            except httpx.HTTPError as exc:
                raise WikimediaImageSearchError(
                    f"Failed to download image from {image_url}: {exc}"
                ) from exc
            results.append(image_response.content)

    return results
