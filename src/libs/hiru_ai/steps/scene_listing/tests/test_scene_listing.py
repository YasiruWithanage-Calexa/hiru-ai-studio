"""The listing is the planner's own, byte for byte (Phase 4 moved it out of the service)."""
from __future__ import annotations

import json
from pathlib import Path

from script_split.engine import planner

from contracts import sceneplan
from hiru_ai.steps.scene_listing import step

HERE = Path(__file__).resolve().parents[1]


def test_it_lists_blocks_exactly_as_the_legacy_planner_did():
    case = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))
    items = sceneplan.scene_items(case["scene"], case["lines"])
    assert step.run(case)["listing"] == planner.scene_listing(items, case["speaker_names"])
    assert "ACTION" in step.run(case)["listing"] and "DIALOGUE (Kasun" in step.run(case)["listing"]
