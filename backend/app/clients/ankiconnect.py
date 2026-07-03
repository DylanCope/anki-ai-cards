"""Async client for the AnkiConnect HTTP API (protocol version 6).

AnkiConnect exposes a single endpoint that accepts
`{"action": ..., "version": 6, "params": {...}}` and replies with
`{"result": ..., "error": ...}`. `error` is non-null on failure.
"""

import os

import httpx


class AnkiConnectError(Exception):
    """Raised when AnkiConnect returns a non-null error."""


def _base_url() -> str:
    return os.environ["ANKICONNECT_URL"]


async def invoke(action: str, *, base_url: str | None = None, **params: object) -> object:
    payload: dict[str, object] = {"action": action, "version": 6}
    if params:
        payload["params"] = params

    async with httpx.AsyncClient() as client:
        response = await client.post(base_url or _base_url(), json=payload)
    response.raise_for_status()
    body = response.json()

    error = body.get("error")
    if error is not None:
        raise AnkiConnectError(f"AnkiConnect action {action!r} failed: {error}")

    return body.get("result")


async def list_note_type_names() -> list[str]:
    return await invoke("modelNames")


async def get_note_type_fields(name: str) -> list[str]:
    return await invoke("modelFieldNames", modelName=name)


async def create_note(
    deck_name: str,
    model_name: str,
    fields: dict[str, str],
    tags: list[str] | None = None,
) -> int:
    note: dict[str, object] = {
        "deckName": deck_name,
        "modelName": model_name,
        "fields": fields,
        "tags": tags or [],
    }
    return await invoke("addNote", note=note)


async def sync() -> None:
    await invoke("sync")
