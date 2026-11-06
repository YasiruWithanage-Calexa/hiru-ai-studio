"""Shot Planner David's vocabulary and the shape of a problem (plan/2026-11-05e §5, §6).

David writes a scene in ONE call, and code judges it. The words a model may use for a size, a join or an addition are
closed lists here; a problem code finds is a `Problem`: an exact sentence, the shots it concerns and WHO fixes it.

Pure standard library + pydantic (the `contracts` rule). Unlike Adam's, David's contracts may name the shared ones
(`contracts.shotplan`, `contracts.stagemap`, `contracts.sceneplan`): the plan reuses the Veo clock as it is (§4.1).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

SIZES: tuple[str, ...] = ("WIDE", "MS", "MCU", "CU", "TWO", "OTS", "INSERT")  # contracts.production.Framing values
LINKS: tuple[str, ...] = ("cut", "continuous", "match")  # contracts.veo.CameraLink values
TAKES: tuple[int, ...] = (4, 6, 8)  # contracts.veo.VEO_DURATIONS

# The closed list of what a director may add (plan §5). Copied from Adam's `contracts/adam/tiers.py`
# (`ELABORATION_KINDS`, plan/2026-11-04b §6.1): the groups stay independent, so the list is copied, not imported.
ADDED_KINDS: tuple[str, ...] = (
    "baseline", "reaction", "listener", "insert_detail", "hands", "pov", "atmosphere", "hold", "plant", "transition",
    "empty_frame", "implied_action", "move",
)
# What each kind must name so that code can check it: the people (all in the scene's cast) and/or an object (in the
# script or on the place card).
NEEDS_WHO: frozenset[str] = frozenset({"baseline", "reaction", "listener", "hands", "pov", "implied_action", "move"})
NEEDS_OBJECT: frozenset[str] = frozenset({"insert_detail", "plant"})

# `scenes.time_of_day` values that say a scene carries on from the one before (contracts.screenplay.TIMES_OF_DAY).
CONTINUOUS_TIMES: frozenset[str] = frozenset({"CONTINUOUS", "MOMENTS LATER", "SAME TIME"})
LinkKind = Literal["continuous", "carry"]  # how a scene follows the one before ("" = it does not)

# Who fixes a problem (plan §6): code mends it, the author is asked (repair), it is dropped, or only reported.
Fix = Literal["mend", "repair", "drop", "report"]
CODES: tuple[str, ...] = (
    "lines", "blocks", "clock", "envelope", "added", "names", "speech", "staging", "heard", "feasibility", "prompt",
    "seam", "end_state", "shape",
)


class Problem(BaseModel):
    """One thing wrong with a plan, as a sentence a person (and the author) can read."""

    model_config = ConfigDict(extra="forbid")

    code: str
    sentence: str
    shots: list[int] = []
    fix: Fix = "repair"
    key: str = ""  # stable across rounds, so a repair that adds a NEW problem is seen as one

    @property
    def id(self) -> str:
        return self.key or f"{self.code}:{self.sentence}"


def norm(name: str) -> str:
    """A name or an object compared the way a person reads it: case and spacing do not matter."""
    return " ".join(str(name).lower().split())
