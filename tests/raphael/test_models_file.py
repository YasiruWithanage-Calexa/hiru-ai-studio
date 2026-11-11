"""Raphael's models are configuration (`core/raphael_models.yaml`), not environment: five tiers fixed in a file."""

from __future__ import annotations

import pytest

from contracts.raphael.money import PRICES
from hiru_ai.core import models
from hiru_ai.core.errors import ManifestError

RAPHAEL_TIERS = ("raphael", "raphael_repair", "raphael_breakdown", "raphael_cinematic", "raphael_cinematic_repair")


def test_the_five_raphael_tiers_are_fixed_in_the_file() -> None:
    assert set(models.load_pins()) == set(RAPHAEL_TIERS)
    for name in RAPHAEL_TIERS:
        tier = models.resolve(name)
        assert tier.model and tier.effort in models.EFFORTS
        assert tier.timeout_s > 0  # the rest of the tier still comes from models.yaml


def test_every_pinned_model_has_a_price() -> None:
    """A model with no price in contracts.raphael.money is refused before any call: catch it here, not in a run."""
    for name, pin in models.load_pins().items():
        assert pin.model in PRICES, f"{name}: {pin.model} has no price in contracts/raphael/money.py"


def test_the_environment_cannot_change_a_pinned_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    before = {n: (models.resolve(n).model, models.resolve(n).effort) for n in RAPHAEL_TIERS}
    for var in ("OPENAI__MODEL_RAPHAEL", "OPENAI__EFFORT_RAPHAEL", "OPENAI__MODEL_RAPHAEL_BREAKDOWN"):
        monkeypatch.setenv(var, "gpt-5" if "MODEL" in var else "low")
    from hiru_ai.core.settings import get_settings

    get_settings.cache_clear()
    try:
        assert {n: (models.resolve(n).model, models.resolve(n).effort) for n in RAPHAEL_TIERS} == before
    finally:
        get_settings.cache_clear()


def test_a_bad_effort_or_an_unknown_key_in_the_file_is_refused(tmp_path) -> None:
    bad = tmp_path / "pins.yaml"
    bad.write_text("tiers:\n  raphael: { model: gpt-5, effort: extreme }\n", encoding="utf-8")
    with pytest.raises(ManifestError):
        models.load_pins.__wrapped__(bad)
    extra = tmp_path / "extra.yaml"
    extra.write_text("tiers:\n  raphael: { model: gpt-5, effort: low, speed: fast }\n", encoding="utf-8")
    with pytest.raises(ManifestError):
        models.load_pins.__wrapped__(extra)
