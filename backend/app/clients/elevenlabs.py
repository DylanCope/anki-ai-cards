"""Async client for the ElevenLabs text-to-speech API.

Generates several audio takes for the same text so Dylan can pick the best
one, by varying voice settings slightly across otherwise-identical requests.
"""

import os

import httpx

API_BASE_URL = "https://api.elevenlabs.io/v1"

# Dylan's own ElevenLabs voices (not the shared/library premade ones task 19
# fell back to). These 402'd with "Free users cannot use library voices via
# the API" on the free tier, same restriction Rachel hit — confirmed fixed
# by Dylan upgrading to a paid ElevenLabs plan (Starter tier or above), not
# by anything in this code. The agent picks one per `voice` ("male"/"female")
# rather than always using a single fixed voice.
VOICE_IDS = {
    "male": "Mv8AjrYZCBkdsmDHNwcB",
    "female": "8EkOjt4xTPGMclNlh1pk",
}
DEFAULT_VOICE = "male"

# Explicit multilingual model so Japanese text is synthesized correctly
# regardless of whatever ElevenLabs defaults `model_id` to server-side.
# Confirmed directly against the real API: omitting `model_id` and passing
# "eleven_multilingual_v2" produce comparable Japanese audio today, but the
# now-deprecated "eleven_monolingual_v1" 401s on this account ("not available
# on the free tier") — pinning to a current multilingual model avoids
# depending on which model an unset `model_id` happens to resolve to.
MODEL_ID = "eleven_multilingual_v2"


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
    text: str, n: int = 3, voice: str = DEFAULT_VOICE
) -> list[bytes]:
    """Generate `n` distinct audio takes for `text` in the given voice
    ("male" or "female"), returning raw audio bytes."""
    try:
        voice_id = VOICE_IDS[voice]
    except KeyError:
        raise ValueError(
            f"Unknown voice {voice!r}; expected one of {sorted(VOICE_IDS)}"
        ) from None

    settings = [_VOICE_SETTINGS_VARIANTS[i % len(_VOICE_SETTINGS_VARIANTS)] for i in range(n)]

    async with httpx.AsyncClient() as client:
        results = []
        for voice_settings in settings:
            response = await client.post(
                f"{API_BASE_URL}/text-to-speech/{voice_id}",
                headers={"xi-api-key": _api_key()},
                json={"text": text, "model_id": MODEL_ID, "voice_settings": voice_settings},
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
