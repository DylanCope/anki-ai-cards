"""Async client for the ElevenLabs text-to-speech API.

Generates several audio takes for the same text so Dylan can pick the best
one, by varying voice settings slightly across otherwise-identical requests.
"""

import os

import httpx

API_BASE_URL = "https://api.elevenlabs.io/v1"

# A default premade ElevenLabs voice (public "Rachel" voice ID). The agent
# layer can pass a different `voice_id` per call if needed later.
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"


class ElevenLabsError(Exception):
    """Raised when the ElevenLabs API returns a non-2xx response.

    Wraps `httpx.HTTPStatusError` to surface ElevenLabs' own JSON `detail`
    message (e.g. "Free users cannot use library voices via the API") instead
    of just httpx's generic "Client error '402 Payment Required'" text, so a
    captured `BugReport` (see `app/api/chat.py`) is diagnosable without
    reproducing the call by hand.
    """


# Stability/similarity_boost pairs used to nudge each of the n options to
# sound slightly different from the others.
_VOICE_SETTINGS_VARIANTS = [
    {"stability": 0.3, "similarity_boost": 0.75},
    {"stability": 0.5, "similarity_boost": 0.75},
    {"stability": 0.7, "similarity_boost": 0.75},
]


def _api_key() -> str:
    return os.environ["ELEVENLABS_API_KEY"]


async def generate_audio_options(
    text: str, n: int = 3, voice_id: str = DEFAULT_VOICE_ID
) -> list[bytes]:
    """Generate `n` distinct audio takes for `text`, returning raw audio bytes."""
    settings = [_VOICE_SETTINGS_VARIANTS[i % len(_VOICE_SETTINGS_VARIANTS)] for i in range(n)]

    async with httpx.AsyncClient() as client:
        results = []
        for voice_settings in settings:
            response = await client.post(
                f"{API_BASE_URL}/text-to-speech/{voice_id}",
                headers={"xi-api-key": _api_key()},
                json={"text": text, "voice_settings": voice_settings},
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                try:
                    api_detail = response.json()["detail"]["message"]
                except (ValueError, KeyError, TypeError):
                    api_detail = response.text
                raise ElevenLabsError(
                    f"ElevenLabs API error ({response.status_code}): {api_detail}"
                ) from exc
            results.append(response.content)

    return results
