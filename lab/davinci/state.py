"""The shoot bin and the memory of one run (plan/2026-11-08d §4.4).

Only code gives a clip its id and its slate. The director changes the edit plan and approves the bin; a worker writes its
own clips' menu entries or designs; the work log records every call. `Bin` is plain data with no model in it, so tests and
the checks read it directly.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schema import Clip, EditPlanW, LookW, MenuW, PlanW


def clean_setup(letter: str) -> str:
    """A setup is one capital letter; anything else becomes A (code owns the shape of ids, setups and slates)."""
    first = (letter.strip()[:1] or "A").upper()
    return first if first.isalpha() else "A"


@dataclass
class Bin:
    scene: str = "1"  # the slate's scene number (D8: the post team's convention replaces this)
    edit: EditPlanW | None = None
    clips: list[Clip] = field(default_factory=list)
    looks: list[LookW] = field(default_factory=list)  # the staged plan's look sheet (plan B §2.1)
    log: list[dict[str, Any]] = field(default_factory=list)
    _next: int = 1

    def by_id(self, clip_id: str) -> Clip | None:
        return next((c for c in self.clips if c.id == clip_id), None)

    def add(self, entry: MenuW) -> Clip:
        """Give a menu entry its id (c01, c02 ...) and put it in the bin."""
        clip = Clip(**entry.model_dump(), id=f"c{self._next:02d}", slate="")
        self._next += 1
        self.clips.append(clip)
        self.reslate()
        return clip

    def load(self, plan: PlanW) -> None:
        """Staged path (plan B §2.2): replace the whole plan at once: the edit plan, the look sheet and every clip. Code
        gives each clip its id (c01 ...), a clean setup letter and its slate; no design survives (there is none yet)."""
        self.edit, self.looks, self.clips, self._next = plan.edit_plan, list(plan.looks), [], 1
        for entry in plan.clips:
            self.add(entry.model_copy(update={"setup": clean_setup(entry.setup)}))

    def remove(self, clip_id: str) -> bool:
        before = len(self.clips)
        self.clips = [c for c in self.clips if c.id != clip_id]
        self.reslate()
        return len(self.clips) != before

    def replace(self, clip_id: str, entry: MenuW) -> Clip | None:
        """Put a new plan in the place of a clip: it keeps its id and its slate position, its design is cleared (the new plan
        needs a new one), and a must clip stays must (a replacement never quietly lowers what the cut uses)."""
        old = self.by_id(clip_id)
        if old is None:
            return None
        fields = entry.model_dump()
        if old.priority == "must":
            fields["priority"] = "must"
        new = Clip(**fields, id=old.id, slate="")
        self.clips[self.clips.index(old)] = new
        self.reslate()
        return new

    def reslate(self) -> None:
        """`12B-3`: scene 12, setup B, the third clip of that setup (by id order), so slates never repeat."""
        seen: dict[str, int] = {}
        for c in sorted(self.clips, key=lambda x: x.id):
            seen[c.setup] = seen.get(c.setup, 0) + 1
            c.slate = f"{self.scene}{c.setup}-{seen[c.setup]}"

    def note(self, **entry: Any) -> None:
        self.log.append(entry)

    def counts(self) -> dict[str, int]:
        out = {"clips": len(self.clips), "written": sum(c.ir is not None for c in self.clips)}
        for p in ("must", "should", "nice"):
            out[p] = sum(c.priority == p for c in self.clips)
        out["take_s"] = sum(c.take_s for c in self.clips)
        out["must_take_s"] = sum(c.take_s for c in self.clips if c.priority == "must")
        return out

    def dump(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "bin.json").write_text(json.dumps([c.model_dump() for c in self.clips], ensure_ascii=False, indent=1),
                                         encoding="utf-8")
        if self.looks:
            (folder / "looks.json").write_text(json.dumps([m.model_dump() for m in self.looks], ensure_ascii=False, indent=1),
                                               encoding="utf-8")
        if self.edit is not None:
            (folder / "edit_plan.json").write_text(self.edit.model_dump_json(indent=1), encoding="utf-8")
        (folder / "work_log.json").write_text(json.dumps(self.log, ensure_ascii=False, indent=1), encoding="utf-8")


def compact(clip: Clip) -> str:
    """One row of the bin as the director reads it."""
    state = "designed" if clip.ir is not None else "menu only"
    speaks = " speaks" if clip.speaks else ""
    lines = f" lines {','.join(clip.lines)}" if clip.lines else ""
    return (f"{clip.id} [{clip.slate}] moment {clip.moment} {clip.priority} {clip.role} {clip.size} {clip.technique} "
            f"{clip.take_s}s handles {clip.handle_in_s:g}/{clip.handle_out_s:g} blocks {clip.blocks}{lines}{speaks} "
            f"({state}): {clip.why}")
