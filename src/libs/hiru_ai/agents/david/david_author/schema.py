"""Typed seams of the david_author agent (plan/2026-11-05e §4.2, §5).

The Input is the scene (for the cleaning after the call) and the context pack `david_pack` built from the database's
rows,
which is the user message as it stands. The Output is the WIRE shape `contracts.david.wire.DavidWire`.
"""
from __future__ import annotations

from pydantic import BaseModel

from contracts.david.scene import SceneS
from contracts.david.wire import DavidWire


class Input(BaseModel):
    scene: SceneS
    pack: str  # the context pack: <production>, <scene>, <start_state>, <last_shot>, <script>


class Output(DavidWire):
    """What the author answers: see `DavidWire`."""
