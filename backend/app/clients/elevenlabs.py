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
            response.raise_for_status()
            results.append(response.content)

    return results
