"""Async client for Jisho.org's public dictionary search API, plus local
word-frequency scoring via `wordfreq`.

Gives the agent real dictionary meanings and a real frequency signal for a
word, so it doesn't have to invent a definition or guess whether a word is
worth a card from its own training-data knowledge alone — same "real source
beats an LLM guess" spirit as `wikimedia_image_search`/`tatoeba`/`forvo`.

Confirmed directly against the real API (2026-07-12):
`GET https://jisho.org/api/v1/search/words?keyword=<query>` (the keyword must
be sent as a normal query param, not appended raw — Jisho 400s on an
un-percent-encoded Japanese keyword) returns
`{"meta": {"status": 200}, "data": [<entry>, ...]}`, `data: []` for no
matches. Each entry is shaped roughly:
`{"slug": str, "is_common": bool, "japanese": [{"word": str | None,
"reading": str}, ...], "senses": [{"english_definitions": [str, ...],
"parts_of_speech": [str, ...], ...}, ...], ...}` — `japanese[0]` is the
entry's most common written form (falls back to its reading alone when the
word has no distinct kanji form, e.g. some particles/adverbs), and
`parts_of_speech` includes non-grammatical values like "Wikipedia definition"
for encyclopedia-style senses, which are kept as-is rather than filtered out.

`wordfreq.zipf_frequency` is a local, offline computation (no network call) —
Japanese tokenization needs the `mecab-python3` + `ipadic` packages installed
alongside `wordfreq` itself (added to pyproject.toml here), since wordfreq's
Japanese support shells out to a MeCab tokenizer rather than tokenizing by
whitespace like most other languages.
"""

from wordfreq import zipf_frequency

import httpx

API_URL = "https://jisho.org/api/v1/search/words"


class DictionaryError(Exception):
    """Raised when Jisho's search API returns a non-2xx response."""


async def search_words(query: str, n: int = 3) -> list[dict]:
    """Search Jisho for dictionary entries matching `query`.

    Returns up to `n` dicts shaped `{"word": str, "readings": [str, ...],
    "meanings": [str, ...], "parts_of_speech": [str, ...], "is_common": bool,
    "frequency": float}` — `frequency` is `wordfreq.zipf_frequency(word,
    "ja")` for the entry's most common written form. Returns an empty list if
    the search finds no results."""
    async with httpx.AsyncClient() as client:
        response = await client.get(API_URL, params={"keyword": query})
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise DictionaryError(
                f"Jisho search API error ({response.status_code}): {response.text}"
            ) from exc

        payload = response.json()

        results = []
        for entry in payload.get("data", [])[:n]:
            japanese = entry.get("japanese", [])
            word = (japanese[0].get("word") or japanese[0].get("reading")) if japanese else entry["slug"]
            readings = [j["reading"] for j in japanese if j.get("reading")]
            meanings = [
                definition
                for sense in entry.get("senses", [])
                for definition in sense.get("english_definitions", [])
            ]
            parts_of_speech = sorted(
                {
                    part
                    for sense in entry.get("senses", [])
                    for part in sense.get("parts_of_speech", [])
                }
            )

            results.append(
                {
                    "word": word,
                    "readings": readings,
                    "meanings": meanings,
                    "parts_of_speech": parts_of_speech,
                    "is_common": bool(entry.get("is_common")),
                    "frequency": zipf_frequency(word, "ja"),
                }
            )

        return results
