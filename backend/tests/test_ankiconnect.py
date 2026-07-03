import json

import pytest
import respx
from httpx import Response

from app.clients import ankiconnect

ANKICONNECT_URL = "http://localhost:8765"


@pytest.fixture(autouse=True)
def _set_ankiconnect_url(monkeypatch):
    monkeypatch.setenv("ANKICONNECT_URL", ANKICONNECT_URL)


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
