"""Async client for the AnkiConnect HTTP API (protocol version 6).

AnkiConnect exposes a single endpoint that accepts
`{"action": ..., "version": 6, "params": {...}}` and replies with
`{"result": ..., "error": ...}`. `error` is non-null on failure.
"""

import asyncio
import os

import httpx


class AnkiConnectError(Exception):
    """Raised when AnkiConnect returns a non-null error."""


# The headless Anki instance segfaults intermittently and auto-restarts
# within a few seconds (base image's own restart loop) — see AGENTS.md's
# "Headless Anki deployment" section. A short retry makes single requests
# resilient to landing in that dead window, without masking a genuinely
# unreachable/misconfigured AnkiConnect (only transient connection-level
# errors are retried, never an AnkiConnect-reported `error` or HTTP status
# error, which indicate a real response was received).
RETRYABLE_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
)
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 2.0


def _base_url() -> str:
    return os.environ["ANKICONNECT_URL"]


async def invoke(action: str, *, base_url: str | None = None, **params: object) -> object:
    payload: dict[str, object] = {"action": action, "version": 6}
    if params:
        payload["params"] = params

    url = base_url or _base_url()

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload)
            response.raise_for_status()
            body = response.json()
            break
        except RETRYABLE_EXCEPTIONS as exc:
            last_error = exc
            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(RETRY_DELAY_SECONDS)
    else:
        raise AnkiConnectError(
            f"AnkiConnect action {action!r} failed after {MAX_ATTEMPTS} attempts "
            f"— the Anki container may be mid-crash-restart: {last_error!r}"
        ) from last_error

    error = body.get("error")
    if error is not None:
        raise AnkiConnectError(f"AnkiConnect action {action!r} failed: {error}")

    return body.get("result")


async def list_note_type_names() -> list[str]:
    return await invoke("modelNames")


async def get_note_type_fields(name: str) -> list[str]:
    return await invoke("modelFieldNames", modelName=name)


async def get_model_templates(name: str) -> dict[str, dict[str, str]]:
    """Wraps `modelTemplates` — result is `{card_name: {"Front": qfmt, "Back":
    afmt}}` per card template defined on the note type, confirmed against
    AnkiConnect's real documented example response."""

    return await invoke("modelTemplates", modelName=name)


async def get_model_styling(name: str) -> str:
    """Wraps `modelStyling` — result is `{"css": <str>}`, confirmed against
    AnkiConnect's real documented example response."""

    result = await invoke("modelStyling", modelName=name)
    return result["css"]


async def get_media_file(filename: str) -> str | None:
    """Wraps `retrieveMediaFile` — result is the file's base64-encoded
    content, or `False` if no file by that name exists in the collection
    (confirmed against the real deployed AnkiConnect instance, both cases).
    Returns `None` for the missing case instead of `False` so callers get a
    normal falsy-but-typed Python value."""

    result = await invoke("retrieveMediaFile", filename=filename)
    return result or None


async def create_note(
    deck_name: str,
    model_name: str,
    fields: dict[str, str],
    tags: list[str] | None = None,
    audio: list[dict[str, object]] | None = None,
    picture: list[dict[str, object]] | None = None,
) -> int:
    """`audio`/`picture`, if given, are lists of AnkiConnect media-attachment
    objects (`{"data": <base64>, "filename": ..., "fields": [...]}`) — one
    entry per attached file, each targeting its own field(s), so a note
    needing several distinct media files (e.g. a word's audio plus a
    separate example-sentence audio) can attach all of them in one call.
    AnkiConnect stores each in the collection's media folder and appends the
    resulting `[sound:filename]`/`<img src="filename">` reference to each of
    its named fields, so callers never need a separate storeMediaFile step.
    `picture` uses the exact same per-entry shape as `audio`, per
    AnkiConnect's addNote documentation (both accept `data`+`filename`+
    `fields` per entry, alongside `url` as an alternative to `data` which
    this client doesn't use)."""

    note: dict[str, object] = {
        "deckName": deck_name,
        "modelName": model_name,
        "fields": fields,
        "tags": tags or [],
    }
    if audio:
        note["audio"] = audio
    if picture:
        note["picture"] = picture
    return await invoke("addNote", note=note)


async def sync() -> None:
    await invoke("sync")
