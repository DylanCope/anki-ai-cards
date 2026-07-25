"""Async client for Azure AI Speech's text-to-speech REST API.

Alternative to ElevenLabs (app.clients.elevenlabs) for Japanese audio.
ElevenLabs has no phoneme/pronunciation-dictionary support for Japanese (only
English), so the only lever against kanji misreadings there is hoping the
model reads plain text correctly. Azure's ja-JP neural voices read kana
directly and correctly, so callers that already know a word's reading can
force correct pronunciation by substituting it in via `segments`, which
`elevenlabs.py`'s plain-text-only interface has no equivalent for.
"""

import os
import xml.sax.saxutils as xml_escape

import httpx

API_BASE_URL_TEMPLATE = "https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"

# Azure's official Japanese-optimized neural voices.
VOICE_IDS = {
    "male": "ja-JP-KeitaNeural",
    "female": "ja-JP-NanamiNeural",
}
DEFAULT_VOICE = "male"

# mp3 so clips stay interchangeable with ElevenLabs' output everywhere else
# in the app (AudioClip has no content_type column — see app/models.py — and
# app/agent/tools.py hardcodes a ".mp3" extension when attaching a clip).
OUTPUT_FORMAT = "audio-48khz-192kbitrate-mono-mp3"

# Rate/pitch nudges, same purpose as elevenlabs._VOICE_SETTINGS_VARIANTS —
# gives each of the n takes a slightly different prosody instead of
# returning n identical clips.
_PROSODY_VARIANTS = [
    {"rate": "0%", "pitch": "0%"},
    {"rate": "-5%", "pitch": "0%"},
    {"rate": "+5%", "pitch": "0%"},
]


class AzureTTSError(Exception):
    """Raised when Azure Speech's REST API returns a non-2xx response.

    Azure's error bodies are plain text/XML, not ElevenLabs' JSON
    `detail.message` shape, so the response text is surfaced as-is.
    """


def _api_key() -> str:
    return os.environ["AZURE_SPEECH_KEY"]


def _region() -> str:
    return os.environ["AZURE_SPEECH_REGION"]


def _build_ssml(segments: list[dict], voice_id: str, prosody: dict) -> str:
    """`segments`: [{"text": str, "reading": str | None}, ...]. Each
    segment's `reading` (kana), when given, is substituted for its `text` in
    the spoken output — Azure's ja-JP voices read kana correctly natively,
    which sidesteps kanji-misreading without needing phoneme tags."""
    body = "".join(
        xml_escape.escape(seg.get("reading") or seg["text"]) for seg in segments
    )
    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="ja-JP">'
        f'<voice name="{voice_id}">'
        f'<prosody rate="{prosody["rate"]}" pitch="{prosody["pitch"]}">{body}</prosody>'
        "</voice></speak>"
    )


async def generate_audio_options(
    text: str,
    n: int = 3,
    voice: str = DEFAULT_VOICE,
    segments: list[dict] | None = None,
) -> list[bytes]:
    """Generate `n` distinct audio takes for `text` in the given voice
    ("male" or "female"), returning raw audio bytes.

    `segments`, if given, is a list of {"text": str, "reading": str | None}
    pairs breaking `text` into pieces with their kana readings attached
    (e.g. [{"text": "明日", "reading": "あした"}, {"text": "行きます"}] for
    "明日行きます") — used to force correct pronunciation per-word instead of
    relying on the voice to read kanji correctly. When omitted, `text` is
    synthesized as-is.
    """
    try:
        voice_id = VOICE_IDS[voice]
    except KeyError:
        raise ValueError(
            f"Unknown voice {voice!r}; expected one of {sorted(VOICE_IDS)}"
        ) from None

    segs = segments or [{"text": text, "reading": None}]
    prosodies = [_PROSODY_VARIANTS[i % len(_PROSODY_VARIANTS)] for i in range(n)]
    url = API_BASE_URL_TEMPLATE.format(region=_region())

    async with httpx.AsyncClient() as client:
        results = []
        for prosody in prosodies:
            ssml = _build_ssml(segs, voice_id, prosody)
            response = await client.post(
                url,
                headers={
                    "Ocp-Apim-Subscription-Key": _api_key(),
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": OUTPUT_FORMAT,
                },
                content=ssml.encode("utf-8"),
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise AzureTTSError(
                    f"Azure Speech API error ({response.status_code}): {response.text}"
                ) from exc
            results.append(response.content)

    return results
