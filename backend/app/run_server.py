"""Entrypoint that binds a genuinely dual-stack socket before starting Uvicorn.

Root cause of the "backend externally unreachable" bug (PRD task 14):
`uvicorn app.main:app --host ::` hands host/port straight to `Uvicorn.Server`,
which -- when given no pre-built socket -- calls asyncio's
`loop.create_server(host=..., port=...)`. That stdlib method unconditionally
sets `IPV6_V6ONLY=1` on any AF_INET6 socket it creates itself (see
`asyncio/base_events.py`, "Disable IPv4/IPv6 dual stack support"), overriding
this machine's OS-level dual-stack default (`bindv6only=0`) regardless of
which event loop backend uvicorn uses. That silently made the deployed
backend refuse IPv4-arriving connections -- including Fly's public health
check and edge proxy, which reach the app over IPv4 -- while still accepting
genuine IPv6 (used by Fly's private 6PN network), which is exactly the
"health check critical, 6PN fine" split this project hit.

`Config.bind_socket()` creates the listening socket itself (plain
`socket.socket()` + `bind()`, no V6ONLY override) and hands it to
`Server.run(sockets=...)`, which skips `create_server`'s host/port branch
entirely -- `create_server(sock=...)` never touches an already-open socket's
options. That keeps the OS's dual-stack default intact, so both IPv4 and
IPv6 callers reach the same listener.
"""

import uvicorn


def main() -> None:
    config = uvicorn.Config("app.main:app", host="::", port=8000)
    server = uvicorn.Server(config)
    sock = config.bind_socket()
    server.run(sockets=[sock])


if __name__ == "__main__":
    main()
