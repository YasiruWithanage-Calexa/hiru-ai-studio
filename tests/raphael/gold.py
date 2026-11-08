"""The gold bins (plan/2026-11-08e phase 2): the lab's run 3 (stage 1, 13 must clips, 70 s) and pass 5 (stage 2: the
same
bin plus 8 cinematic clips, 112 s), saved from the paid runs of 2026-11-08, and the Episode 1 scene they were made for.
They are fixed points: the checks find no blocking fault in either."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from contracts.raphael.bin import Bin
from contracts.raphael.scene import Brief, SceneS
from contracts.raphael.wire import Clip, EditPlanW, ReviewRow

FIXTURES = Path(__file__).parent / "fixtures"


def _json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def scene_file() -> dict[str, Any]:
    return dict(_json("scene.json"))


def scene() -> SceneS:
    return SceneS.model_validate(scene_file()["scene"])


def brief() -> Brief:
    return Brief(scene=scene(), guide_s=float(scene_file()["guide_s"]))


def edit_plan() -> EditPlanW:
    return EditPlanW.model_validate(_json("edit_plan.json"))


def _bin(name: str) -> Bin:
    work = Bin(scene="1")
    work.edit = edit_plan()
    work.clips = [Clip.model_validate(r) for r in _json(name)]
    work.next_no = max(int(c.id[1:]) for c in work.clips) + 1
    return work


def stage1() -> Bin:
    """Stage 1's finished bin: 13 must clips."""
    return _bin("stage1_bin.json")


def final() -> Bin:
    """Stage 2's finished bin: stage 1's 13 clips and 8 cinematic clips."""
    return _bin("final_bin.json")


def stage2_result() -> tuple[list[str], list[ReviewRow]]:
    data = _json("stage2_result.json")
    return list(data["blend_notes"]), [ReviewRow.model_validate(r) for r in data["moment_review"]]
