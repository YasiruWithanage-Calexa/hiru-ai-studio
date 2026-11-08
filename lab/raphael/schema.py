"""The shapes of the Raphael lab (plan/2026-11-08e §2, §3.2).

Raphael delivers what DaVinci delivers, so the intended cut (`EditPlanW`), a clip's plan (`MenuW`), the bin entry (`Clip`)
and the closed lists (roles, priorities, techniques) are DaVinci's, imported (R2: one copy, so both labs are judged the same).

New here is one shape: `ClipW`, a whole clip as ONE model writes it, plan and Veo design together. It is DaVinci's `MenuW`
plus the clip writer's `IrW` (`ir`, `sound`) and an `id`: "" for a new clip (code gives the id and the slate), or the id of a
clip in the bin to replace it.
"""
from __future__ import annotations

from typing import Any

from contracts.david.wire import SoundW, _Wire
from davinci.schema import TECHNIQUES, Clip, EditPlanW, MenuW, design_schema, edit_schema

SCHEMA_PUT = "put_clips"


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


__all__ = ["TECHNIQUES", "Clip", "ClipW", "EditPlanW", "MenuW", "PutW", "edit_schema", "put_schema"]
