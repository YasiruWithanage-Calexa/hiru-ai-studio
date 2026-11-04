"""Typed seams of the adam_sound_designer agent (plan/2026-11-04b §5.1 `SoundMap`, §5.2).

The Output is the WIRE shape (`contracts.adam.wire.SoundWire`). `Output.sound_map()` gives the plan's `SoundMap`;
`Output.apply(cards)` gives the cards with the sound written for them.
"""
from __future__ import annotations

from pydantic import BaseModel

from contracts.adam.plan import Moment, SceneScript, ShotCard, Treatment
from contracts.adam.wire import SoundWire


class Input(BaseModel):
    scene: SceneScript
    treatment: Treatment  # the chosen one, with its moment ids bound
    moments: list[Moment]
    cards: list[ShotCard]  # the designer's cards that passed fidelity; the sound field is what this agent rewrites


class Output(SoundWire):
    """What the sound designer answers: see `SoundWire`."""
