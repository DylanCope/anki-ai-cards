# Extends the prebuilt ankimcp/headless-anki image (x11-vnc variant) with a
# socat TCP relay in front of AnkiConnect. See entrypoint.sh and AGENTS.md's
# "AnkiConnect must be reached via Flycast" section for the full story:
# AnkiConnect's own hand-rolled HTTP server reliably handles genuine loopback
# connections but resets connections arriving via Fly's Flycast/private proxy.
# This relay makes every connection AnkiConnect sees a real loopback
# connection, regardless of how Flycast delivers it on the other side.
#
# Base image's own CMD is ["/startup.sh"] (backgrounds Xvfb/openbox/x11vnc,
# then loops running `anki -b /data` in the foreground) — entrypoint.sh
# starts the relay first, then execs straight into that same script
# unchanged.
FROM ghcr.io/ankimcp/headless-anki:x11-vnc-v1.0.0

RUN apt-get update && apt-get install -y --no-install-recommends socat \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /anki-ai-cards-entrypoint.sh
RUN chmod +x /anki-ai-cards-entrypoint.sh

CMD ["/anki-ai-cards-entrypoint.sh"]
