import pytest
import respx
from httpx import Response

from app.clients import fly_api

MACHINES_URL = f"{fly_api.MACHINES_API_BASE_URL}/apps/{fly_api.ANKI_APP_NAME}/machines"


@pytest.fixture(autouse=True)
def _set_fly_api_token(monkeypatch):
    monkeypatch.setenv("FLY_API_TOKEN", "test-token")


@respx.mock
async def test_restart_anki_machines_restarts_every_machine():
    respx.get(MACHINES_URL).mock(
        return_value=Response(200, json=[{"id": "abc123"}, {"id": "def456"}])
    )
    restart_abc = respx.post(f"{MACHINES_URL}/abc123/restart").mock(
        return_value=Response(200, json={})
    )
    restart_def = respx.post(f"{MACHINES_URL}/def456/restart").mock(
        return_value=Response(200, json={})
    )

    await fly_api.restart_anki_machines()

    assert restart_abc.called
    assert restart_def.called
    sent_auth = respx.calls.last.request.headers["Authorization"]
    assert sent_auth == "Bearer test-token"


@respx.mock
async def test_restart_anki_machines_raises_on_list_failure():
    respx.get(MACHINES_URL).mock(return_value=Response(500))

    with pytest.raises(Exception):
        await fly_api.restart_anki_machines()
