"""The shapes of the Raphael lab (plan/2026-11-08e §2, §3.2).

Raphael delivers what DaVinci delivers, so the intended cut (`EditPlanW`), a clip's plan (`MenuW`), the bin entry (`Clip`)
and the closed lists (roles, priorities, techniques) are DaVinci's, imported (R2: one copy, so both labs are judged the same).

New here is one shape: `ClipW`, a whole clip as ONE model writes it, plan and Veo design together. It is DaVinci's `MenuW`
plus the clip writer's `IrW` (`ir`, `sound`) and an `id`: "" for a new clip (code gives the id and the slate), or the id of a
clip in the bin to replace it.

Stage 2 (the cinematic pass, §3.5) adds `ExtraW` (a `ClipW` that is never `must`, with `anchor` and `blend`) and `Extra`, the
bin entry it becomes (`stage` 2).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from contracts.david.wire import SoundW, _Wire
from davinci.schema import TECHNIQUES, Clip, EditPlanW, MenuW, design_schema, edit_schema

SCHEMA_PUT = "put_clips"
SCHEMA_EXTRAS = "put_extras"
Blend = Literal["cut_in", "under_line", "open", "close", "transition"]
BLENDS: tuple[str, ...] = ("cut_in", "under_line", "open", "close", "transition")
# the roles a cinematic clip usually takes (§2.2): named in the prompt, not enforced (the blocking rule is "differs from its anchor")
CINEMATIC_ROLES: tuple[str, ...] = ("insert", "cutaway", "reaction", "establishing", "atmosphere", "pov", "transition_out",
                                    "transition_in")


class ClipW(MenuW):
    id: str  # "" for a new clip; the id of a clip in the bin (c07) to replace it
    ir: dict[str, Any]  # setting, cinematography{...}, lighting, subjects[], beats[], audio, first_frame{...}
    sound: SoundW

    def menu(self) -> MenuW:
        return MenuW.model_validate(self.model_dump(exclude={"id", "ir", "sound"}))


class PutW(_Wire):
    clips: list[ClipW]


def put_schema() -> dict[str, Any]:
    return design_schema(PutW, SCHEMA_PUT)


# ── stage 2: the cinematic pass (§2.2, §3.5) ─────────────────────────────────────────────────────


class ExtraW(ClipW):
    """A cinematic clip as stage 2 writes it: a whole clip (plan + design), never `must`, with the must clip(s) it sits with
    and how post blends it in."""

    priority: Literal["should", "nice"]  # the schema itself refuses `must`: the must clips are stage 1's
    anchor: list[str]  # the must clip id(s) it sits with (c07); for `transition`, a must clip of the neighbouring moment may be one
    blend: Blend  # cut_in | under_line | open | close | transition


class ExtrasW(_Wire):
    clips: list[ExtraW]


class Extra(Clip):
    """A bin entry written by stage 2. Stage 1's clips stay plain `Clip` (stage 1) and are never touched."""

    stage: int = 2
    anchor: list[str] = Field(default_factory=list)
    blend: str = ""


def extras_schema() -> dict[str, Any]:
    return design_schema(ExtrasW, SCHEMA_EXTRAS)


__all__ = ["BLENDS", "CINEMATIC_ROLES", "TECHNIQUES", "Clip", "ClipW", "EditPlanW", "Extra", "ExtraW", "ExtrasW", "MenuW",
           "PutW", "edit_schema", "extras_schema", "put_schema"]
