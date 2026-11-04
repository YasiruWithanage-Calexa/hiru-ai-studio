"""Typed seams of the adam_director agent (plan/2026-11-04b §5.1 `Treatment`, §5.2).

The Output is the WIRE shape (`contracts.adam.wire.TreatmentsWire`): three treatments, one per stance. `Output.all()`
gives the plan's `Treatment`s; their moment ids are empty until the moment writer binds them.
"""
from __future__ import annotations

from pydantic import BaseModel

from contracts.adam.plan import SceneAnalysis, SceneScript
from contracts.adam.wire import TreatmentsWire


class Input(BaseModel):
    scene: SceneScript
    analysis: SceneAnalysis
    before: str = ""  # the scene before: its heading and how it ends, for the way into this one
    after: str = ""  # the scene after: its heading and how it starts, for the way out
    devices: str = ""  # passages of the device library the system retrieved (the agent cannot search)


class Output(TreatmentsWire):
    """What the director answers: see `TreatmentsWire`."""
