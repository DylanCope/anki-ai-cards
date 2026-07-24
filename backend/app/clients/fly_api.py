"""Async client for Fly.io's Machines API.

Used only by `app.watchdog` to restart the headless Anki app
(`anki-ai-cards-anki`) when it wedges — see that module's docstring for why.
Scoped to exactly that one operation; not a general Fly API wrapper.
"""

import os

import httpx

MACHINES_API_BASE_URL = "https://api.machines.dev/v1"
ANKI_APP_NAME = "anki-ai-cards-anki"


def _api_token() -> str:
    return os.environ["FLY_API_TOKEN"]


async def restart_anki_machines() -> None:
    """Restart every machine in the headless Anki app. Production only ever
    runs one, but this doesn't assume that."""

    headers = {"Authorization": f"Bearer {_api_token()}"}
    async with httpx.AsyncClient(base_url=MACHINES_API_BASE_URL, headers=headers) as client:
        response = await client.get(f"/apps/{ANKI_APP_NAME}/machines")
        response.raise_for_status()
        for machine in response.json():
            restart_response = await client.post(
                f"/apps/{ANKI_APP_NAME}/machines/{machine['id']}/restart"
            )
            restart_response.raise_for_status()
