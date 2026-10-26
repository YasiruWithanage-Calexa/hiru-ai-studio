"""The continuity ledger — what the next shot needs to know about the ones before it.

Forked from PromptMotion `nova_producer/engine/continuity.py` (1d748dc). Two lifetimes, kept
apart on purpose:

  - **Identity** (`characters`) persists across every cut, seeded from the canon cards (the
    wardrobe anchor and appearance), because a cut to a new place is exactly where a character
    silently changes face and clothes.
  - **Scene state** (`setting`, `lighting`, `last_action`) persists only inside a scene.

Hiru divergence: no `revealed` world facts (Hiru shots carry no `out_state`; the approved script
is the story), and identity is seeded from canon cards rather than a treatment's cast.
"""
from __future__ import annotations

from typing import Any

from contracts.producer import CastMember, identity_line
from shot_producer.engine.model import ShotInput

_FIELD_CHARS = 240


def _clip(text: object, limit: int = _FIELD_CHARS) -> str:
    return " ".join(str(text or "").split())[:limit]


class ContinuityLedger:
    def __init__(self, cast: list[CastMember]) -> None:
        self.characters: dict[str, CastMember] = {c.id: c for c in cast}
        self.scene_id = ""
        self.setting = self.lighting = self.last_action = ""
        self.last_code = ""

    def observe(self, scene_id: str, shot: ShotInput, ir: dict[str, Any]) -> None:
        if scene_id != self.scene_id:
            self.scene_id = scene_id
            self.setting = self.lighting = self.last_action = ""
        self.setting = _clip(ir.get("setting")) or self.setting
        self.lighting = _clip(ir.get("lighting")) or self.lighting
        beats = [b for b in (ir.get("beats") or []) if isinstance(b, dict)]
        if beats:
            self.last_action = _clip(beats[-1].get("action")) or self.last_action
        self.last_code = shot.code

    def identity_block(self, shot: ShotInput) -> str:
        states = [self.characters[c.id] for c in shot.cast if c.id in self.characters]
        if not states:
            return ""
        return ("THESE PEOPLE ALREADY EXIST — match them exactly, this is not a fresh design:\n"
                + "\n".join(f"- {identity_line(s)}" for s in states))

    def scene_block(self, scene_id: str) -> str:
        if not self.scene_id or scene_id != self.scene_id:
            return ""
        bits = [f"Location: {self.setting}" if self.setting else "",
                f"Light: {self.lighting}" if self.lighting else "",
                f"Picks up from {self.last_code}: {self.last_action}" if self.last_action else ""]
        bits = [b for b in bits if b]
        return "CONTINUES THE SAME SCENE:\n" + "\n".join(f"- {b}" for b in bits) if bits else ""


def carried_state(previous_code: str, previous_ir: dict[str, Any] | None) -> str:
    """For a joined shot's prompt: where the previous shot left the place, the light and the action."""
    if not previous_ir:
        return ""
    beats = [b for b in (previous_ir.get("beats") or []) if isinstance(b, dict)]
    bits = [f"Location: {_clip(previous_ir.get('setting'))}" if previous_ir.get("setting") else "",
            f"Light: {_clip(previous_ir.get('lighting'))}" if previous_ir.get("lighting") else "",
            f"{previous_code} ended on: {_clip(beats[-1].get('action'))}" if beats and beats[-1].get("action") else ""]
    return ". ".join(b for b in bits if b)
