import respx
from httpx import ConnectError, Response

from scripts import smoke_test_ankiconnect

STUB_URL = "http://stub-ankiconnect:8765"


@respx.mock
async def test_check_ankiconnect_returns_version():
    respx.post(STUB_URL).mock(return_value=Response(200, json={"result": 6, "error": None}))

    version = await smoke_test_ankiconnect.check_ankiconnect(STUB_URL)

    assert version == 6


@respx.mock
def test_main_prints_ok_and_returns_zero_on_success(capsys):
    respx.post(STUB_URL).mock(return_value=Response(200, json={"result": 6, "error": None}))

    exit_code = smoke_test_ankiconnect.main(["--url", STUB_URL])

    assert exit_code == 0
    assert "ok" in capsys.readouterr().out


@respx.mock
def test_main_prints_error_and_returns_one_on_unreachable_server(capsys):
    respx.post(STUB_URL).mock(side_effect=ConnectError("connection refused"))

    exit_code = smoke_test_ankiconnect.main(["--url", STUB_URL])

    assert exit_code == 1
    assert "error" in capsys.readouterr().err


@respx.mock
def test_main_prints_error_and_returns_one_on_ankiconnect_error(capsys):
    respx.post(STUB_URL).mock(
        return_value=Response(200, json={"result": None, "error": "boom"})
    )

    exit_code = smoke_test_ankiconnect.main(["--url", STUB_URL])

    assert exit_code == 1
    assert "boom" in capsys.readouterr().err


def test_main_returns_one_when_no_url_given(monkeypatch, capsys):
    monkeypatch.delenv("ANKICONNECT_URL", raising=False)

    exit_code = smoke_test_ankiconnect.main([])

    assert exit_code == 1
    assert "no --url" in capsys.readouterr().err


@respx.mock
def test_main_falls_back_to_env_var(monkeypatch, capsys):
    monkeypatch.setenv("ANKICONNECT_URL", STUB_URL)
    respx.post(STUB_URL).mock(return_value=Response(200, json={"result": 6, "error": None}))

    exit_code = smoke_test_ankiconnect.main([])

    assert exit_code == 0
    assert "ok" in capsys.readouterr().out
