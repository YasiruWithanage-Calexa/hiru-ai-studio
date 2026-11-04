"""Typed seams of the adam_critic_opportunity agent (plan/2026-11-04b §5.4). The Input is the plan so far; the Output is
the wire shape of a critic (`contracts.adam.screening.CriticWire`): at most four notes and a 1 to 5 score on its own
lens."""
from __future__ import annotations

from contracts.adam.screening import CriticWire, ScreenInput


class Input(ScreenInput):
    """What a critic is given: see `ScreenInput`."""


class Output(CriticWire):
    """What a critic answers: see `CriticWire`."""
