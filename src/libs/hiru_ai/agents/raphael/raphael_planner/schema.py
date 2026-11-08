"""Typed seams of the raphael_planner agent (plan/2026-11-08e §3.1).

The Input is the first message (built by `contracts.raphael.pack`) and what the code tools need to judge a bin: the
scene,
the length the script gives, the slate's scene number, the techniques the visual language allows and the turn cap. The
Output says only how the conversation ended; the result is the session's bin (the caller holds the session).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from contracts.raphael.scene import SceneS
from contracts.raphael.tools import STAGE1_TURNS
from contracts.raphael.wire import TECHNIQUES


class Input(BaseModel):
    opening: str  # the first message: <production>, <scene>, <script>, <voice_only>, <length>
    scene: SceneS
    guide_s: float = 0.0  # the length the script gives: the TARGET
    scene_no: str = "1"  # the slate's scene number
    allowed: list[str] = Field(default_factory=lambda: list(TECHNIQUES))  # the production's visual language
    max_turns: int = STAGE1_TURNS  # R1, plan/2026-11-08f §4


class Output(BaseModel):
    stopped: str = ""  # finished | turns | idle | cap | stuck | error
