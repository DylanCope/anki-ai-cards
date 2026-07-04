import json

import httpx
import pytest
import respx
from httpx import Response

from app.clients import ankiconnect

ANKICONNECT_URL = "http://localhost:8765"


@pytest.fixture(autouse=True)
def _set_ankiconnect_url(monkeypatch):
    monkeypatch.setenv("ANKICONNECT_URL", ANKICONNECT_URL)
    # No real delays in tests — retry backoff is only for production, where
    # it gives Anki's crash-restart loop (a few seconds, see AGENTS.md) time
    # to come back up.
    monkeypatch.setattr(ankiconnect, "RETRY_DELAY_SECONDS", 0)


@respx.mock
async def test_invoke_returns_result_on_success():
    route = respx.post(ANKICONNECT_URL).mock(
        return_value=Response(200, json={"result": 6, "error": None})
    )

    result = await ankiconnect.invoke("version")

    assert result == 6
    assert route.called
    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body == {"action": "version", "version": 6}


@respx.mock
async def test_invoke_raises_on_error():
    respx.post(ANKICONNECT_URL).mock(
        return_value=Response(200, json={"result": None, "error": "deck was not found"})
    )

    with pytest.raises(ankiconnect.AnkiConnectError, match="deck was not found"):
        await ankiconnect.invoke("addNote", note={})


@respx.mock
async def test_list_note_type_names():
    respx.post(ANKICONNECT_URL).mock(
        return_value=Response(
            200, json={"result": ["Basic", "Cloze"], "error": None}
        )
    )

    result = await ankiconnect.list_note_type_names()

    assert result == ["Basic", "Cloze"]


@respx.mock
async def test_get_note_type_fields():
    route = respx.post(ANKICONNECT_URL).mock(
        return_value=Response(200, json={"result": ["Text", "Extra"], "error": None})
    )

    result = await ankiconnect.get_note_type_fields("Cloze")

    assert result == ["Text", "Extra"]
    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body["params"] == {"modelName": "Cloze"}


@respx.mock
async def test_create_note():
    route = respx.post(ANKICONNECT_URL).mock(
        return_value=Response(200, json={"result": 12345, "error": None})
    )

    note_id = await ankiconnect.create_note(
        deck_name="Japanese",
        model_name="Cloze",
        fields={"Text": "{{c1::食べる}}", "Extra": "to eat"},
        tags=["lesson"],
    )

    assert note_id == 12345
    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body["params"]["note"] == {
        "deckName": "Japanese",
        "modelName": "Cloze",
        "fields": {"Text": "{{c1::食べる}}", "Extra": "to eat"},
        "tags": ["lesson"],
    }


@respx.mock
async def test_sync():
    route = respx.post(ANKICONNECT_URL).mock(
        return_value=Response(200, json={"result": None, "error": None})
    )

    await ankiconnect.sync()

    assert route.called


@respx.mock
async def test_invoke_retries_transient_connection_errors_then_succeeds():
    route = respx.post(ANKICONNECT_URL).mock(
        side_effect=[
            httpx.ConnectError("connection refused"),
            httpx.ReadError("connection reset"),
            Response(200, json={"result": 6, "error": None}),
        ]
    )

    result = await ankiconnect.invoke("version")

    assert result == 6
    assert route.call_count == 3


@respx.mock
async def test_invoke_raises_after_exhausting_retries():
    route = respx.post(ANKICONNECT_URL).mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    with pytest.raises(ankiconnect.AnkiConnectError, match="failed after 3 attempts"):
        await ankiconnect.invoke("version")

    assert route.call_count == ankiconnect.MAX_ATTEMPTS


@respx.mock
async def test_invoke_does_not_retry_an_ankiconnect_reported_error():
    route = respx.post(ANKICONNECT_URL).mock(
        return_value=Response(200, json={"result": None, "error": "deck was not found"})
    )

    with pytest.raises(ankiconnect.AnkiConnectError, match="deck was not found"):
        await ankiconnect.invoke("addNote", note={})

    assert route.call_count == 1
