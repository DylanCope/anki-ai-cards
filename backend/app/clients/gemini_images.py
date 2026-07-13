"""Async client for Gemini's image-generation-capable models.

Generates several images for the same prompt so Dylan can pick the best one,
mirroring `elevenlabs.generate_audio_options`'s "call N times for N options"
shape — the caller (the `generate_image` tool in `app/agent/tools.py`) is
responsible for persisting the returned bytes and handing back stable ids,
not this module. Reuses the same `GEMINI_API_KEY`/`genai.Client` construction
already established in `app/agent/providers/gemini_provider.py` rather than
duplicating auth handling.
"""

import os

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

# Confirmed directly against the real API (2026-07-11, via `fly ssh console`
# against the deployed backend's real GEMINI_API_KEY: `client.models.list()`
# filtered for image-capable models, then a real `generate_content` call
# against this exact model id) — see PROGRESS.md's task 37 entry for the
# full trace. "gemini-3.1-flash-image" is Gemini's current non-preview
# image-generation model, reached via the same `generateContent` action the
# rest of this codebase already uses (not the separate Imagen `predict` API).
# The real call returned 429 RESOURCE_EXHAUSTED specifically scoped to this
# model on the free tier (not a 404/model-not-found), which confirms the
# model id itself is valid and live — the same "confirmed id, blocked by
# account tier" situation model_registry.py already documents for its
# Gemini 3.x chat models.
MODEL_ID = "gemini-3.1-flash-image"


class GeminiImageError(Exception):
    """Raised when the Gemini API returns an error, or a response contains
    no image data to extract."""


def _client() -> genai.Client:
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _extract_image_bytes(response: types.GenerateContentResponse) -> bytes | None:
    candidate = response.candidates[0] if response.candidates else None
    parts = candidate.content.parts if candidate and candidate.content else []
    for part in parts:
        if part.inline_data and part.inline_data.data:
            return part.inline_data.data
    return None


async def generate_images(prompt: str, n: int = 3) -> list[bytes]:
    """Generate `n` distinct images for `prompt`, returning raw image bytes."""
    client = _client()
    config = types.GenerateContentConfig(response_modalities=[types.Modality.IMAGE])

    results = []
    for _ in range(n):
        try:
            response = await client.aio.models.generate_content(
                model=MODEL_ID, contents=prompt, config=config
            )
        except genai_errors.APIError as exc:
            raise GeminiImageError(
                f"Gemini image generation error ({exc.code}): {exc.message}"
            ) from exc

        image_bytes = _extract_image_bytes(response)
        if image_bytes is None:
            raise GeminiImageError("Gemini response contained no image data")
        results.append(image_bytes)

    return results
