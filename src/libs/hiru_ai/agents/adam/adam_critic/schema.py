"""Typed seams of the adam_critic agent (plan/2026-11-05 T4). The Input is the plan so far with the code's report (the
fidelity lens reads it); the Output is the wire shape `contracts.adam.wire.CriticsWire`: notes tagged by lens and one
score
for each."""
from __future__ import annotations

from contracts.adam.screening import ScreenInput
from contracts.adam.wire import CriticsWire


class Input(ScreenInput):
    """What the critic is given: see `ScreenInput`."""


class Output(CriticsWire):
    """What the critic answers: see `CriticsWire`."""
