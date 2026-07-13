from unittest.mock import MagicMock, patch

from app.run_server import main


def test_main_binds_a_socket_and_passes_it_to_server_run():
    # Regression test for PRD task 14: `uvicorn app.main:app --host ::`
    # (no pre-bound socket) routes through asyncio's `create_server(host=,
    # port=)`, which forces IPV6_V6ONLY=1 and makes the backend refuse
    # IPv4 (Fly's public health check/proxy) while still accepting IPv6
    # (Fly's private 6PN). `main()` must instead call `Config.bind_socket()`
    # itself and pass the resulting socket to `Server.run(sockets=...)`,
    # which skips that host/port code path entirely.
    fake_sock = object()
    with (
        patch("app.run_server.uvicorn.Config") as mock_config_cls,
        patch("app.run_server.uvicorn.Server") as mock_server_cls,
    ):
        mock_config = mock_config_cls.return_value
        mock_config.bind_socket.return_value = fake_sock
        mock_server = mock_server_cls.return_value

        main()

        mock_config_cls.assert_called_once_with("app.main:app", host="::", port=8000)
        mock_server_cls.assert_called_once_with(mock_config)
        mock_server.run.assert_called_once_with(sockets=[fake_sock])
