"""Typed seams of the shot_prompter agent (plan/2026-11-20d §3; `lab/shot_prompts/run.py`). The agent writes ONE
opening state and, from it, the first frame's words and the video's direction; the `shot_prompt` step builds what it is
given (the brief), checks its answer (D6) and assembles both prompts, so every fact stays code's: the lines' words, the
reference citations, the identity lines, the camera sentence, the rules and the format.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Person(BaseModel):
    """One person in frame at the instant the clip begins."""

    name: str
    side: Literal["left", "centre", "right"]
    facing: str
    posture: str
    hands: str
    expression: str


class Opening(BaseModel):
    people: list[Person]
    background: str
    light: str


class Frame(BaseModel):
    """The still: no motion."""

    composition: str = Field(description="camera height and angle in physical words, lens look, framing at the "
                                         "move's start, where each person sits, foreground and depth")
    people: str
    background: str
    light: str


class Step(BaseModel):
    """One beat of the clip, in order."""

    kind: Literal["action", "line"]
    text: str = Field(description="An action step: what happens, one or two sentences. A line step: empty.")
    line_id: str = Field(description="A line step: the line's id as the brief gives it. An action step: empty.")
    to: str = Field(description="A line step: who it is said to ('herself' when muttered). An action step: empty.")
    how: str = Field(description="A line step: the delivery, a phrase. An action step: empty.")
    listener: str = Field(description="A line step: what the listener does. Empty when nobody else is there.")
    # lab/timecodes (2026-11-21): Google's timecodes. Code prints them as "[start-ends] " before the step.
    start_s: float = Field(description="When this step starts, in seconds from the clip's start (0 for the first).")
    end_s: float = Field(description="When it ends: the next step's start; the last step ends at the take length.")


class Video(BaseModel):
    situation: str
    people: str
    flow: list[Step]
    sound: str


class ShotPrompts(BaseModel):
    """The agent's answer: one opening state, the frame and the video that follow it."""

    opening: Opening
    frame: Frame
    video: Video


class Input(BaseModel):
    """What the step built for one shot."""

    scene: str  # the <scene> part: identical for every shot of the scene, sent as its own message first (it caches)
    shot: str  # the <shot> part: the facts
    camera: str  # the <camera> part: the Camera agent's design for the shot (or the panel's camera)
    cards: list[str] = Field(default_factory=list)  # the craft cards code picked for this shot, by name
    mode: Literal["both", "video_only"] = "both"
    fixed: str = ""  # video_only: the stored opening and frame, as JSON, to be returned unchanged
    # plan/2026-11-22c: a person's direction for how the shot PLAYS (a softer voice, calmer, slower), for the video only
    video_note: str = ""
    repair: list[str] = Field(default_factory=list)  # the first answer's faults, on the repair call only
    previous: str = ""  # the first answer as JSON, on the repair call only
