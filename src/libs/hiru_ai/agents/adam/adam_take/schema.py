"""Typed seams of the adam_take agent (plan/2026-11-05 T1).

The Input is what the five stage agents were given between them, plus the facts code already knows (so the model does
not work them out in its reasoning). The Output is the WIRE shape `contracts.adam.wire.TakeWire`; `Output.plan()`
turns it into the plan's parts through the methods the stages use.
"""
from __future__ import annotations

from pydantic import BaseModel

from contracts.adam.plan import SceneAnalysis, SceneScript
from contracts.adam.wire import TakeWire


class Character(BaseModel):
    name: str
    summary: str = ""


class Context(BaseModel):
    """What surrounds the scene. Everything is optional: a plan is made from whatever is known (copied from the
    dramaturg's: parts never import each other)."""

    heading: str = ""
    note: str = ""  # the director's note on the scene
    episode_title: str = ""
    synopsis: str = ""
    before: str = ""  # the scene before: its heading and what happens
    after: str = ""
    characters: list[Character] = []


class Input(BaseModel):
    scene: SceneScript
    context: Context = Context()
    grammar: str = ""  # passages of the film-grammar principles the system retrieved (the agent cannot search)
    devices: str = ""  # passages of the device library
    facts: str = ""  # what code already knows: each line's words and the shortest take that holds it (`facts_of`)
    removed: list[str] = []  # elaborations a person took out, in words: they must not come back
    analysis: SceneAnalysis | None = None  # a treatment switch: the stored analysis, which is kept and not rewritten
    # a person's choice of treatment ("restrained", "intimate", "heightened"); empty = the model chooses
    stance: str = ""
    notes: str = ""  # what code refused in the last attempt (the system retries once); empty on the first try


class Output(TakeWire):
    """What the take answers: see `TakeWire`."""
