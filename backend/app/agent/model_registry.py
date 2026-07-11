"""The catalogue of models Dylan can pick between for the inner agent.

Pricing is per-million-tokens, cached at the time this file was written
(2026-07) — Anthropic and Google both revise pricing periodically, so treat
these as informative for the picker UI, not a billing guarantee.
"""

from dataclasses import dataclass
from typing import Literal

Provider = Literal["anthropic", "gemini"]


@dataclass(frozen=True)
class ModelInfo:
    id: str
    provider: Provider
    display_name: str
    input_price_per_mtok: float
    output_price_per_mtok: float
    description: str


AVAILABLE_MODELS: list[ModelInfo] = [
    ModelInfo(
        id="claude-opus-4-8",
        provider="anthropic",
        display_name="Claude Opus 4.8",
        input_price_per_mtok=5.00,
        output_price_per_mtok=25.00,
        description="Anthropic's most capable model — best for tricky doc-parsing or field-mapping calls.",
    ),
    ModelInfo(
        id="claude-sonnet-5",
        provider="anthropic",
        display_name="Claude Sonnet 5",
        input_price_per_mtok=3.00,
        output_price_per_mtok=15.00,
        description="Strong balance of capability and cost — a good default for most card-creation turns.",
    ),
    ModelInfo(
        id="claude-haiku-4-5",
        provider="anthropic",
        display_name="Claude Haiku 4.5",
        input_price_per_mtok=1.00,
        output_price_per_mtok=5.00,
        description="Anthropic's fastest, cheapest model — fine for simple lookups and confirmations.",
    ),
    # The whole Gemini 2.5 generation (Pro/Flash/Flash-Lite) 404s with "no
    # longer available to new users" on Dylan's API key — confirmed directly
    # against the real API (2026-07-10), not assumed from docs. These 3.x
    # IDs are what's actually reachable on his key today; empirically
    # verified live: gemini-3.1-flash-lite responds reliably (including
    # function calling); gemini-3-flash-preview and gemini-3.1-pro-preview
    # exist and accept requests but hit 429 (quota) or 503 (overloaded) on
    # a free-tier key — likely fine once Dylan enables billing, kept in the
    # picker rather than removed since the restriction is account-tier, not
    # a real unavailability.
    ModelInfo(
        id="gemini-3.1-pro-preview",
        provider="gemini",
        display_name="Gemini 3.1 Pro (preview)",
        input_price_per_mtok=2.00,
        output_price_per_mtok=12.00,
        description="Google's most capable current Gemini model. On a free-tier API key this may hit quota limits — needs billing enabled for reliable use.",
    ),
    ModelInfo(
        id="gemini-3-flash-preview",
        provider="gemini",
        display_name="Gemini 3 Flash (preview)",
        input_price_per_mtok=0.50,
        output_price_per_mtok=3.00,
        description="Cheaper than Opus at solid quality. Preview model — occasionally returns 'overloaded' errors.",
    ),
    ModelInfo(
        id="gemini-3.1-flash-lite",
        provider="gemini",
        display_name="Gemini 3.1 Flash-Lite",
        input_price_per_mtok=0.25,
        output_price_per_mtok=1.50,
        description="Google's cheapest reliable model — confirmed working end to end, including tool calls, on a free-tier key.",
    ),
]

DEFAULT_MODEL_ID = "gemini-3.1-flash-lite"

_MODELS_BY_ID = {model.id: model for model in AVAILABLE_MODELS}


def get_model(model_id: str) -> ModelInfo:
    try:
        return _MODELS_BY_ID[model_id]
    except KeyError:
        raise ValueError(f"Unknown model id: {model_id!r}") from None
