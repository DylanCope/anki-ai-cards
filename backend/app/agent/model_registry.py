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
    ModelInfo(
        id="gemini-2.5-pro",
        provider="gemini",
        display_name="Gemini 2.5 Pro",
        input_price_per_mtok=1.25,
        output_price_per_mtok=10.00,
        description="Google's most capable Gemini model — cheaper than Opus at broadly comparable quality.",
    ),
    ModelInfo(
        id="gemini-2.5-flash",
        provider="gemini",
        display_name="Gemini 2.5 Flash",
        input_price_per_mtok=0.30,
        output_price_per_mtok=2.50,
        description="Fast and inexpensive — a good everyday default if you want to conserve Anthropic credits.",
    ),
    ModelInfo(
        id="gemini-2.5-flash-lite",
        provider="gemini",
        display_name="Gemini 2.5 Flash-Lite",
        input_price_per_mtok=0.10,
        output_price_per_mtok=0.40,
        description="Google's cheapest model — for simple, low-stakes turns where cost matters most.",
    ),
]

DEFAULT_MODEL_ID = "claude-opus-4-8"

_MODELS_BY_ID = {model.id: model for model in AVAILABLE_MODELS}


def get_model(model_id: str) -> ModelInfo:
    try:
        return _MODELS_BY_ID[model_id]
    except KeyError:
        raise ValueError(f"Unknown model id: {model_id!r}") from None
