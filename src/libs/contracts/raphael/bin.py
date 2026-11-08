"""The shoot bin and the memory of one run (plan/2026-11-08e §3.4, phase 1).

Only code gives a clip its id and its slate. Raphael changes the edit plan and writes clips; the work log records every
call. `Bin` is plain data with no model in it, so tests and the checks read it directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from contracts.raphael.wire import Clip, EditPlanW, MenuW


def clean_setup(letter: str) -> str:
    """A setup is one capital letter; anything else becomes A (code owns the shape of ids, setups and slates)."""
    first = (letter.strip()[:1] or "A").upper()
    return first if first.isalpha() else "A"


@dataclass
class Bin:
    scene: str = "1"  # the slate's scene number
    edit: EditPlanW | None = None
    clips: list[Clip] = field(default_factory=list)
    log: list[dict[str, Any]] = field(default_factory=list)
    next_no: int = 1

    def by_id(self, clip_id: str) -> Clip | None:
        return next((c for c in self.clips if c.id == clip_id), None)

    def musts(self) -> list[Clip]:
        return [c for c in self.clips if not c.is_extra]

    def extras(self) -> list[Clip]:
        return [c for c in self.clips if c.is_extra]

    def add(self, entry: MenuW, *, stage: int = 1, anchor: list[str] | None = None, blend: str = "") -> Clip:
        """Give a plan its id (c01, c02 ...) and put it in the bin."""
        fields = entry.model_dump()
        fields["setup"] = clean_setup(str(fields["setup"]))
        clip = Clip(**fields, id=f"c{self.next_no:02d}", slate="", stage=stage, anchor=list(anchor or []), blend=blend)
        self.next_no += 1
        self.clips.append(clip)
        self.reslate()
        return clip

    def remove(self, clip_id: str) -> bool:
        before = len(self.clips)
        self.clips = [c for c in self.clips if c.id != clip_id]
        self.reslate()
        return len(self.clips) != before

    def replace(
        self, clip_id: str, entry: MenuW, *, anchor: list[str] | None = None, blend: str | None = None
    ) -> Clip | None:
        """Put a new plan in the place of a clip: it keeps its id, its stage and its slate position, and a must clip
        stays
        must (a replacement never quietly lowers what the cut uses)."""
        old = self.by_id(clip_id)
        if old is None:
            return None
        fields = entry.model_dump()
        fields["setup"] = clean_setup(str(fields["setup"]))
        if old.priority == "must":
            fields["priority"] = "must"
        new = Clip(
            **fields,
            id=old.id,
            slate="",
            stage=old.stage,
            anchor=list(old.anchor if anchor is None else anchor),
            blend=old.blend if blend is None else blend,
        )
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
        out["extra_take_s"] = sum(c.take_s for c in self.clips if c.is_extra)
        return out


def compact(clip: Clip) -> str:
    """One row of the bin as the agent reads it."""
    state = "designed" if clip.ir is not None else "menu only"
    speaks = " speaks" if clip.speaks else ""
    lines = f" lines {','.join(clip.lines)}" if clip.lines else ""
    return (
        f"{clip.id} [{clip.slate}] moment {clip.moment} {clip.priority} {clip.role} {clip.size} {clip.technique} "
        f"{clip.take_s}s handles {clip.handle_in_s:g}/{clip.handle_out_s:g} blocks {clip.blocks}{lines}{speaks} "
        f"({state}): {clip.why}"
    )
