"""Typed seams of the david_repair agent (plan/2026-11-05e §4.2).

The Input is the scene, the plan as it stands, the exact problems (sentences code wrote), the shots they involve and
what an
earlier round tried. The Output is the WIRE shape `contracts.david.wire.PatchWire`: replacements, never a new plan.
"""
from __future__ import annotations

from pydantic import BaseModel

from contracts.david.plan import Problem
from contracts.david.scene import SceneS
from contracts.david.wire import DavidWire, PatchWire


class Input(BaseModel):
    scene: SceneS
    plan: DavidWire
    problems: list[Problem]
    tried: list[str] = []  # what an earlier round changed, in sentences: do not undo it, do not repeat it
    note: str = ""  # a person's note on the plan, when this repair is theirs (the David tab's "plan again with a note")


class Output(PatchWire):
    """What the repairer answers: see `PatchWire`."""
