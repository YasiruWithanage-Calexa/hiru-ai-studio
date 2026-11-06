"""Typed seams of the adam_dramaturg agent (plan/2026-11-04b §5.1 `SceneAnalysis`, §5.2).

The Output is the WIRE shape (`contracts.adam.wire.AnalysisWire`): what the model is held to in strict JSON-schema mode.
`Output.analysis()` turns it into the plan's `SceneAnalysis`.
"""
from __future__ import annotations

from pydantic import BaseModel

from contracts.adam.plan import SceneScript
from contracts.adam.wire import AnalysisWire


class Character(BaseModel):
    name: str
    summary: str = ""


class Context(BaseModel):
    """What surrounds the scene. Everything is optional: an analysis is made from whatever is known."""

    heading: str = ""
    note: str = ""  # the director's note on the scene
    episode_title: str = ""
    episode: int | None = None  # its number, for the production memory's `episode:` entries
    synopsis: str = ""
    before: str = ""  # the scene before: its heading and what happens
    after: str = ""
    characters: list[Character] = []


class Input(BaseModel):
    scene: SceneScript
    context: Context = Context()
    grammar: str = ""  # passages of the film-grammar principles the system retrieved (the agent cannot search)


class Output(AnalysisWire):
    """What the dramaturg answers: see `AnalysisWire`."""
