"""Async client for asking a Gemini multimodal model a question that can
embed existing audio/image assets inline, not just plain text.

Deliberately generic — this module has no idea what an AudioClip or
ImageAsset is. `app.agent.tools`'s `ask_multimodal_model` tool is what
parses `[[audio_clip_<id>]]`/`[[image_<id>]]` placeholders out of the
agent's prompt and resolves them against the DB; this module just takes an
ordered list of text/media parts and returns the model's text reply, so the
same call works for any media type Gemini accepts inline (audio and images
confirmed; video would slot in the same way if a video asset type existed).
"""

import os

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

# Confirmed directly against the real API via `fly ssh console` against the
# deployed backend's real GEMINI_API_KEY: sent two real audio clips with a
# comparison prompt ("which sounds more natural") and got back a coherent,
# correctly-reasoned answer. gemini-3.1-flash-lite (already this app's
# DEFAULT_MODEL_ID for chat, per app/agent/model_registry.py — confirmed
# reliable on a free-tier key) gave an equally good answer as
# gemini-3.1-pro-preview on the same prompt, so it's used here too rather
# than the pricier preview model.
MODEL_ID = "gemini-3.1-flash-lite"


class GeminiMultimodalError(Exception):
    """Raised when the Gemini API returns an error, or a response contains
    no text to return."""


def _client() -> genai.Client:
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _to_content_part(part: dict) -> str | types.Part:
    if "text" in part:
        return part["text"]
    return types.Part.from_bytes(data=part["data"], mime_type=part["mime_type"])


async def ask(parts: list[dict]) -> str:
    """Send an ordered list of parts to Gemini and return its text reply.

    Each entry in `parts` is either {"text": str} or {"data": bytes,
    "mime_type": str} — order is preserved in the request, so a prompt like
    [{"text": "Option A:"}, {"data": ..., "mime_type": "audio/mpeg"},
    {"text": "Option B:"}, {"data": ..., "mime_type": "audio/mpeg"}]
    reaches the model with each label immediately before its clip, the same
    way a human reader would follow it.
    """
    client = _client()
    contents = [_to_content_part(part) for part in parts]

    try:
        response = await client.aio.models.generate_content(model=MODEL_ID, contents=contents)
    except genai_errors.APIError as exc:
        raise GeminiMultimodalError(
            f"Gemini multimodal error ({exc.code}): {exc.message}"
        ) from exc

    if not response.text:
        raise GeminiMultimodalError("Gemini response contained no text")
    return response.text
