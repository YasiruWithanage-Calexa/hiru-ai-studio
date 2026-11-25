"""Typed seams of the board_counter agent (plan/2026-11-25, lab/board_hands R5: `Count`, `Thing`, `Blind`)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Input(BaseModel):
    image_b64: str  # one painted Scene board panel (or a blocking plate), base64
    mime: str = "image/png"
    mannequins: list[str] = []  # the colours of the mannequins the panel shows ("red", "blue"): nothing else


class Count(BaseModel):
    mannequin: str = Field(description="The mannequin's colour.")
    arms: int = Field(description="Arms of this mannequin you can see, whole or in part, each traced from its "
                                  "shoulder; an arm hidden behind the body or cut by the frame is not counted.")
    hands: int = Field(description="Hands you can see that belong to this mannequin, on its arms or not.")
    hands_hold: list[str] = Field(description="One entry per hand counted: what it holds or does ('the umbrella "
                                              "shaft', 'the phone at the ear', 'empty, at the hip').")


class Thing(BaseModel):
    thing: str = Field(description="What it is: 'umbrella', 'bag', 'phone'.")
    mannequin: str = Field(description="The colour of the mannequin it belongs to, or 'none'.")
    where: str = Field(description="'hand', 'surface' or 'air', as the instructions say.")


class Output(BaseModel):
    counts: list[Count] = Field(description="One entry per mannequin in the picture.")
    things: list[Thing] = Field(description="Every thing a mannequin holds or carries.")
