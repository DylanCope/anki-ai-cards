"""Async client for the ElevenLabs text-to-speech API.

Generates several audio takes for the same text so Dylan can pick the best
one, by varying voice settings slightly across otherwise-identical requests.
"""

import os

import httpx

API_BASE_URL = "https://api.elevenlabs.io/v1"

# ElevenLabs' own library voices "Ishibashi" (male) and "Morioki" (female),
# both marketed by ElevenLabs specifically as Japanese-optimized voices —
# not ad-hoc clones, despite what an earlier version of this comment claimed.
# These 402'd with "Free users cannot use library voices via the API" on the
# free tier, same restriction Rachel hit — confirmed fixed by Dylan
# upgrading to a paid ElevenLabs plan (Starter tier or above), not by
# anything in this code. The agent picks one per `voice` ("male"/"female")
# rather than always using a single fixed voice.
VOICE_IDS = {
    "male": "Mv8AjrYZCBkdsmDHNwcB",
    "female": "8EkOjt4xTPGMclNlh1pk",
}
DEFAULT_VOICE = "male"

# ElevenLabs doesn't infer language from voice alone for multilingual
# models — passing this explicitly avoids the model guessing wrong on short
# or ambiguous strings, one contributor to the kanji-misreading complaints
# task 18/19 partially addressed via the furigana prompt workaround.
LANGUAGE_CODE = "ja"

# eleven_v3 (GA since Feb 2026) over the previously-pinned
# eleven_multilingual_v2: ElevenLabs' own material and third-party Japanese
# reviews both point to v3 as the more natural-sounding model for Japanese,
# and v3 is required for `LANGUAGE_CODE` to take effect at all —
# multilingual_v2 rejects the `language_code` field outright. v3 costs
# noticeably more per character than multilingual_v2 (see ElevenLabs
# pricing), which is worth knowing if usage volume grows, but is
# negligible at this app's flashcard-audio volume.
MODEL_ID = "eleven_v3"


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
                json={
                    "text": text,
                    "model_id": MODEL_ID,
                    "language_code": LANGUAGE_CODE,
                    "voice_settings": voice_settings,
                },
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
