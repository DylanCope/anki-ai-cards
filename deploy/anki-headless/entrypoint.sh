#!/bin/bash
# Relays connections on port 8766 (what Flycast/[http_service] actually
# exposes, per fly.toml) to AnkiConnect's real listener at 127.0.0.1:8765.
#
# AnkiConnect's own HTTP server is a hand-rolled, single-threaded, select()-
# based implementation (see AGENTS.md's "AnkiConnect must be reached via
# Flycast" section) that reliably handles genuine loopback connections but
# resets connections arriving via Fly's Flycast/private proxy layer. This
# relay's only job is to make sure AnkiConnect only ever sees the former —
# a real loopback connection — no matter how Flycast delivers bytes on the
# other side.
socat TCP-LISTEN:8766,fork,reuseaddr TCP:127.0.0.1:8765 &

exec /startup.sh
