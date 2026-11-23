"""Typed seams of the board_inspector agent."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Input(BaseModel):
    image_b64: str  # one painted Scene board panel, base64
    mime: str = "image/png"
    people: list[str] = []  # "Anudi is the blue mannequin": who the panel shows, by colour
    panel: str = ""  # what the panel should show: its camera and picture
    hands: str = ""  # `contracts.board.hands_text`: each mannequin's left and right hand, "" = no hand check


class Output(BaseModel):
    extra_limbs: bool = Field(description="A mannequin has more or fewer than two arms, or more or fewer than two "
                                          "hands or legs.")
    floating: bool = Field(description="A held thing (umbrella, phone, bag, cup) is in the air with no hand "
                                       "gripping it, or hangs from nothing.")
    ungrounded: bool = Field(description="A standing or walking mannequin's feet do not rest on the ground: they hover "
                                         "over a drain, a step, an edge or empty space.")
    hands_match: bool = Field(default=True, description=(
        "Each mannequin's hands hold what HANDS says, in the hand it says. True when HANDS is absent."))
    problems: list[str] = Field(description="At most three short faults, each naming the mannequin by colour and "
                                            "what is wrong; empty when the panel is fine.")
