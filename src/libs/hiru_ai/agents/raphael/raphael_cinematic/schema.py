"""Typed seams of the raphael_cinematic agent (plan/2026-11-08e §3.5).

The Input is the first message and stage 1's finished result, which the pass reads and may not change: the scene, the
intended cut and the must clips. The Output says only how the conversation ended.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from contracts.raphael.scene import SceneS
from contracts.raphael.tools import STAGE2_TURNS
from contracts.raphael.wire import DEFAULT_CAP, TECHNIQUES, Clip, EditPlanW


class Input(BaseModel):
    opening: str  # the first message: everything stage 1 had, the intended cut, the must bin, the looks and the room
    scene: SceneS
    guide_s: float = 0.0
    scene_no: str = "1"
    edit: EditPlanW  # stage 1's intended cut
    clips: list[Clip]  # stage 1's finished bin (the must clips): LOCKED
    cap: float = DEFAULT_CAP  # the length cap used (the person's choice, §2.1)
    allowed: list[str] = Field(default_factory=lambda: list(TECHNIQUES))
    max_turns: int = STAGE2_TURNS  # S4, plan/2026-11-08f §4


class Output(BaseModel):
    stopped: str = ""  # finished | turns | idle | cap | stuck | error
