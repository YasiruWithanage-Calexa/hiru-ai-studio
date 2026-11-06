"""Typed seams of the jonathan_author agent (plan/2026-11-05e §4.2, §5).

The Input is the scene (for the cleaning after the call) and the context pack `jonathan_pack` built from the database's
rows,
which is the user message as it stands. The Output is the WIRE shape `contracts.jonathan.wire.JonathanWire`.
"""
from __future__ import annotations

from pydantic import BaseModel

from contracts.jonathan.scene import SceneS
from contracts.jonathan.wire import JonathanWire


class Input(BaseModel):
    scene: SceneS
    pack: str  # the context pack: <production>, <scene>, <start_state>, <last_shot>, <script>


class Output(JonathanWire):
    """What the author answers: see `JonathanWire`."""
