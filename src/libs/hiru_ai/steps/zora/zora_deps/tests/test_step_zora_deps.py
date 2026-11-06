"""Tests that live with the zora_deps step (ADR 0006)."""
from __future__ import annotations

import json
from pathlib import Path

from hiru_ai.steps.zora.zora_deps import step

HERE = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))


def test_an_added_shot_is_a_task_for_its_picture_scoped_to_it():
    out = step.run(EXAMPLE)
    (task,) = out["tasks"]
    assert task["scope"] == [3] and "shot.why" in task["writes"] and out["offer"] == ""


def test_a_retime_needs_no_author():
    out = step.run({**EXAMPLE, "ops": [{"op": "retime", "shot": 2, "take_s": 6}]})
    assert out["tasks"] == [] and out["stale"] == [2]
