"""Background watchdog for the headless Anki app's known wedge failure mode.

Anki's own AnkiWeb-sync attempt can block its single-threaded process for
hours with no crash and no further log output (bug report #31, 2026-07-24;
first seen 2026-07-10, see PROGRESS.md for both). Fly's own `http_service`
health checks can't recover this on their own — confirmed against Fly's
docs/community answers that a failing check only ever affects Fly Proxy
traffic routing, never triggers a restart, and `anki-ai-cards-anki` has no
public traffic to route anyway (Flycast-only).

This polls AnkiConnect's `version` action on a timer and restarts the Anki
app via the Fly Machines API (`app.clients.fly_api`) if it stops responding,
with a cooldown so one incident doesn't trigger repeated restarts before
Anki has had a chance to boot back up (~45s observed cold-start).
"""

import asyncio
import time

from app.clients import ankiconnect, fly_api

POLL_INTERVAL_SECONDS = 60
RESTART_COOLDOWN_SECONDS = 300


async def _is_anki_responsive() -> bool:
    try:
        await ankiconnect.invoke("version")
    except Exception:
        return False
    return True


class Watchdog:
    """Split out from `run_watchdog`'s loop so a single check-and-maybe-
    restart pass (the actual logic worth testing) doesn't require fighting
    `asyncio.sleep` in tests."""

    def __init__(self) -> None:
        # -inf, not 0.0: time.monotonic()'s reference point is arbitrary
        # (often since boot on Linux), so a fresh process could see a small
        # value here — 0.0 would then make the very first wedge incorrectly
        # look like it's still within the cooldown of a "restart" that never
        # happened.
        self._last_restart = float("-inf")

    async def check_once(self) -> None:
        if await _is_anki_responsive():
            return
        if time.monotonic() - self._last_restart < RESTART_COOLDOWN_SECONDS:
            return
        self._last_restart = time.monotonic()
        try:
            await fly_api.restart_anki_machines()
        except Exception:
            pass


async def run_watchdog() -> None:
    watchdog = Watchdog()
    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        await watchdog.check_once()
