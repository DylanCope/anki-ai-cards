import respx
from httpx import ConnectError, Response

from scripts import smoke_test_chat

STUB_URL = "http://stub-backend:8000"


@respx.mock
def test_send_chat_message_returns_reply():
    respx.post(f"{STUB_URL}/api/chat").mock(
        return_value=Response(200, json={"reply": "Your note types are: Basic, Cloze", "payloads": []})
    )

    reply = smoke_test_chat.send_chat_message(STUB_URL, "List my Anki note types.", "test-key")

    assert reply == "Your note types are: Basic, Cloze"


@respx.mock
def test_send_chat_message_sends_bearer_header():
    route = respx.post(f"{STUB_URL}/api/chat").mock(
        return_value=Response(200, json={"reply": "ok", "payloads": []})
    )

    smoke_test_chat.send_chat_message(STUB_URL, "hi", "test-key")

    assert route.calls.last.request.headers["Authorization"] == "Bearer test-key"


@respx.mock
def test_main_prints_ok_and_returns_zero_on_success(monkeypatch, capsys):
    monkeypatch.setenv("DEV_API_KEY", "test-key")
    respx.post(f"{STUB_URL}/api/chat").mock(
        return_value=Response(200, json={"reply": "Basic, Cloze", "payloads": []})
    )

    exit_code = smoke_test_chat.main(["--url", STUB_URL])

    assert exit_code == 0
    assert "ok" in capsys.readouterr().out


@respx.mock
def test_main_prints_error_and_returns_one_on_unreachable_server(monkeypatch, capsys):
    monkeypatch.setenv("DEV_API_KEY", "test-key")
    respx.post(f"{STUB_URL}/api/chat").mock(side_effect=ConnectError("connection refused"))

    exit_code = smoke_test_chat.main(["--url", STUB_URL])

    assert exit_code == 1
    assert "error" in capsys.readouterr().err


@respx.mock
def test_main_prints_error_and_returns_one_on_http_error(monkeypatch, capsys):
    monkeypatch.setenv("DEV_API_KEY", "test-key")
    respx.post(f"{STUB_URL}/api/chat").mock(return_value=Response(401, json={"detail": "Not authenticated"}))

    exit_code = smoke_test_chat.main(["--url", STUB_URL])

    assert exit_code == 1
    assert "401" in capsys.readouterr().err


def test_main_returns_one_when_dev_api_key_unset(monkeypatch, capsys):
    monkeypatch.delenv("DEV_API_KEY", raising=False)

    exit_code = smoke_test_chat.main(["--url", STUB_URL])

    assert exit_code == 1
    assert "DEV_API_KEY" in capsys.readouterr().err
