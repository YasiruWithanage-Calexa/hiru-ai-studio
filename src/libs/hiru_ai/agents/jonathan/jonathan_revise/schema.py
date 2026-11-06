"""Typed seams of the jonathan_revise agent (plan/2026-11-06b §4.1, the cinematic lab's revise pass).

The Input is what the author was given (the scene and the context pack), the author's own draft as code mended it, and
what code found in it: the hard problems (sentences code wrote) and the craft gaps (measures it missed). A person's
note,
when this pass is theirs. The Output is the WIRE shape `contracts.jonathan.wire.JonathanWire`: the whole corrected plan.
"""
from __future__ import annotations

from pydantic import BaseModel

from contracts.jonathan.measures import Measure
from contracts.jonathan.plan import Problem
from contracts.jonathan.scene import SceneS
from contracts.jonathan.wire import JonathanWire


class Input(BaseModel):
    scene: SceneS
    pack: str  # the author's own user message: <production>, <scene>, <start_state>, <last_shot>, <script>
    draft: JonathanWire  # the best plan so far (the author's draft, or a better revise of it), as code mended it
    problems: list[Problem] = []  # the hard problems: fix every one
    gaps: list[Measure] = []  # the craft measures missed: improve them where the scene allows it
    # a person's note on the plan, when this pass is theirs (the Jonathan tab's "plan again with a note")
    note: str = ""


class Output(JonathanWire):
    """What the reviser answers: the complete corrected plan (see `JonathanWire`)."""
