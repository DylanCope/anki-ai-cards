# Extends the prebuilt ankimcp/headless-anki image (x11-vnc variant) with:
#
# 1. A socat TCP relay in front of AnkiConnect. See entrypoint.sh and
#    AGENTS.md's "AnkiConnect must be reached via Flycast" section for the
#    full story: AnkiConnect's own hand-rolled HTTP server reliably handles
#    genuine loopback connections but resets connections arriving via Fly's
#    Flycast/private proxy. This relay makes every connection AnkiConnect
#    sees a real loopback connection, regardless of how Flycast delivers it.
# 2. A D-Bus system bus. Anki's Qt/WebEngine (Chromium) UI logs
#    "Failed to connect to the bus: ... /run/dbus/system_bus_socket: No such
#    file or directory" and then segfaults intermittently a few seconds
#    later in this environment (no D-Bus was running at all) — see AGENTS.md.
#    Providing one is a low-risk attempt to remove that as a variable. Even
#    if it doesn't fully eliminate the crash, the base image's own restart
#    loop (/startup.sh) recovers within a couple seconds regardless, and the
#    backend's AnkiConnect client (backend/app/clients/ankiconnect.py) now
#    retries transient connection failures as a second line of defense.
#
# Base image's own CMD is ["/startup.sh"] (backgrounds Xvfb/openbox/x11vnc,
# then loops running `anki -b /data` in the foreground) — entrypoint.sh
# starts the relay and dbus first, then execs straight into that same script
# unchanged.
FROM ghcr.io/ankimcp/headless-anki:x11-vnc-v1.0.0

RUN apt-get update && apt-get install -y --no-install-recommends socat dbus \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /anki-ai-cards-entrypoint.sh
RUN chmod +x /anki-ai-cards-entrypoint.sh

CMD ["/anki-ai-cards-entrypoint.sh"]
