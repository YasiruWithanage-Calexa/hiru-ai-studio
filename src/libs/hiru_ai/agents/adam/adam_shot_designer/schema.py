"""Typed seams of the adam_shot_designer agent (plan/2026-11-04b §5.1 `ShotCard`, §5.2).

The Output is the WIRE shape (`contracts.adam.wire.CardsWire`). `Output.card_list()` gives the plan's `ShotCard`s,
numbered by their place in the list.
"""
from __future__ import annotations

from pydantic import BaseModel

from contracts.adam.plan import Moment, SceneAnalysis, SceneScript, Staging, Treatment
from contracts.adam.wire import CardsWire


class Input(BaseModel):
    scene: SceneScript
    analysis: SceneAnalysis
    treatment: Treatment  # the chosen one, with its moment ids bound
    moments: list[Moment]  # the moments that passed fidelity, in order
    staging: Staging = Staging()
    devices: str = ""  # passages of the device library the system retrieved (the agent cannot search)
    notes: str = ""  # what code refused in the last attempt (the system retries once); empty on the first try
    required: list[str] = []  # the faces the analysis says must be seen, in words (`adam_coverage`); empty = none
    episode: int | None = None  # the scene's episode number, for the production memory's `episode:` entries


class Output(CardsWire):
    """What the shot designer answers: see `CardsWire`."""
