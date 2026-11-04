"""Typed seams of the adam_moment_writer agent (plan/2026-11-04b §5.1 `Moment`, §5.2).

The Output is the WIRE shape (`contracts.adam.wire.MomentsWire`): the moments in the order the viewer lives them, and
the ids of the moments that carry the plant, its payoff, the rhythm break, the ending image and the point-of-view
handover. `Output.moment_list()` gives the plan's `Moment`s; `Output.bind()` writes the ids into the analysis and the
treatment.
"""
from __future__ import annotations

from pydantic import BaseModel

from contracts.adam.plan import SceneAnalysis, SceneScript, Treatment
from contracts.adam.wire import MomentsWire


class Input(BaseModel):
    scene: SceneScript
    analysis: SceneAnalysis
    treatment: Treatment  # the chosen one; its moment ids are still empty
    notes: str = ""  # what code refused in the last attempt (the system retries once); empty on the first try


class Output(MomentsWire):
    """What the moment writer answers: see `MomentsWire`."""
