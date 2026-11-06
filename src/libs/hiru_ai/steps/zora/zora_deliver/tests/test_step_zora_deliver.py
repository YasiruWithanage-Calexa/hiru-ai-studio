"""Tests that live with the zora_deliver step (ADR 0006)."""
from __future__ import annotations

import json
from pathlib import Path

from hiru_ai.steps.zora.zora_deliver import step

HERE = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))


def test_the_lens_was_delivered_the_angle_was_not_and_is_retasked_once():
    out = step.run(EXAMPLE)
    assert out["missing"] == ["shot.angle"] and out["report"] == ["the shots' angle"]
    assert out["retask"][0]["writes"] == ["shot.angle"] and out["retask"][0]["origin"] == "delivery"
