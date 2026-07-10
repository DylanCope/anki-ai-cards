import pytest

from app.agent import model_registry


def test_default_model_is_in_available_models():
    ids = [model.id for model in model_registry.AVAILABLE_MODELS]
    assert model_registry.DEFAULT_MODEL_ID in ids


def test_available_models_span_both_providers():
    providers = {model.provider for model in model_registry.AVAILABLE_MODELS}
    assert providers == {"anthropic", "gemini"}


def test_get_model_returns_matching_model():
    model = model_registry.get_model("gemini-2.5-flash")

    assert model.id == "gemini-2.5-flash"
    assert model.provider == "gemini"


def test_get_model_raises_for_unknown_id():
    with pytest.raises(ValueError, match="Unknown model id"):
        model_registry.get_model("gpt-4o")
