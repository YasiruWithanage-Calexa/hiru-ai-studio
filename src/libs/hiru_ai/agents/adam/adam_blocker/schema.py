"""Typed seams of the adam_blocker agent (plan/2026-11-04b §5.1 `Staging`, §5.2).

The Output is the WIRE shape (`contracts.adam.wire.StagingWire`). `Output.staging()` gives the plan's `Staging`.
"""
from __future__ import annotations

from pydantic import BaseModel

from contracts.adam.plan import Moment, SceneAnalysis, SceneScript, Treatment
from contracts.adam.wire import StagingWire


class Input(BaseModel):
    scene: SceneScript  # its place (a name and the objects the location card has) is the location card
    analysis: SceneAnalysis  # who wants what, whose scene it is
    treatment: Treatment  # the chosen one, with its moment ids bound
    moments: list[Moment]  # the moments that passed fidelity, in order


class Output(StagingWire):
    """What the blocker answers: see `StagingWire`."""
