"""Try row-kernel operations on a copy of the open scene's shot rows (plan/2026-11-13 phase 8: Sable's change cards
through the row kernel, `steps/coverage_kernel`, instead of the classic director function).

Two Sable tools need the same trial (`sable_shot_try`, `sable_shot_change`), and a tool never imports another tool, so
the trial lives here, over the scene store and the kernel found by id. Nothing is saved: the kernel works on a copy read
from the rows. Operations are tried as the `author`'s: a field a person locked is refused, and nothing gets a lock (the
person's Accept replays them the same way and saves them in place, `core.coverage_rows`, as a revision the scene's
chat can undo).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from contracts.coverage import checks, risk
from contracts.coverage.ledger import changes, where
from contracts.coverage.scene import Coverage
from hiru_ai.core import parts, tooling
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ToolRefused
from hiru_ai.core.trial import OPEN_FIRST, OTHER_SCENE

Row = dict[str, Any]
BY = "author"  # a model's: never writes a person's lock, never locks
MAX_OPS = 12
OpName = Literal["set", "retime", "sound", "sound_mode", "role", "insert", "remove", "split", "merge", "move", "line",
                 "note"]


class RowOp(BaseModel):
    """One operation on the shot rows: `op` and only the fields it uses."""

    op: OpName
    shot: int | None = Field(None, description="The shot's number as the scene shows it now (2 for S02)")
    field: str | None = Field(None, description="set: size, link, why, sees, angle, lens, movement, setting, "
                                                "lighting, audio; sound: ambience, effects, music, silence")
    value: str | None = Field(None, description="The new value (set, sound, sound_mode, note)")
    take_s: int | None = Field(None, description="retime / insert: 4, 6 or 8")
    role: str | None = Field(None, description="role / insert: master, two_shot, single, ots, wide, reaction, insert")
    priority: str | None = Field(None, description="role / insert: must, should or nice")
    size: str | None = Field(None, description="insert: the new clip's size, like CU")
    after: str | None = Field(None, description='insert / move: the shot number it goes after, or "start"')
    first_block: int | None = Field(None, description="insert: the first block the new clip shows")
    last_block: int | None = Field(None, description="insert: the last block it shows")
    who: list[str] | None = Field(None, description="insert: the people on screen, by name")
    what: str | None = Field(None, description="insert: what the new clip shows, in plain words")
    at_block: int | None = Field(None, description="split: the block the second half starts at")
    to_shot: int | None = Field(None, description="merge: the shot folded in; line: the shot that performs it")
    line: str | None = Field(None, description='line: the line, as "L" + its block number ("L5" for b5)')

    def as_op(self) -> Row:
        return {k: v for k, v in self.model_dump().items() if v is not None and v != []}


@dataclass
class RowTrial:
    scene: Row
    before: Coverage
    after: Coverage
    applied: list[Row]  # {op, by, text}
    rejected: list[Row]  # {op, reason}
    notes: list[str]  # what the kernel did on its own (a line moved to another clip)
    made_on: str  # the rows' fingerprint as read: Accept is refused once they change
    done: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return tooling.scene_label(self.scene)

    def rows(self, ops: list[Row]) -> list[Row]:
        """One `{op, applied, why?}` per operation sent, in the order sent."""
        refused = {id(r["op"]): r["reason"] for r in self.rejected}
        texts = {id(a["op"]): a["text"] for a in self.applied}
        return [{"op": texts.get(id(o)) or str(o.get("op")), "applied": id(o) not in refused,
                 **({"why": refused[id(o)]} if id(o) in refused else {})} for o in ops]

    def problems(self) -> list[str]:
        """The new problems the change leaves (the checks, report only here: a person decides)."""
        return [f.sentence for f in checks.new(self.before, self.after)]

    def risks(self) -> list[str]:
        """Why the scene's chat would ask first (`contracts.coverage.risk`), for the card."""
        found = checks.repairable(checks.new(self.before, self.after))
        return risk.reasons(self.applied, self.before, self.after, found)

    def touched(self) -> list[str]:
        return sorted({where(x) for x in self.done} - {"Scene"})

    def timing(self) -> Row:
        return {"takes_s": self.after.total_s(), "was_s": self.before.total_s(), "target_s": self.after.target_s,
                "shots": len(self.after.clips)}


def scene_of(ctx: RunContext, scene_ref: str | None) -> tuple[Any, Row]:
    """The open scene, or a refusal: Sable changes only the scene in view (plan/2026-11-09b D1/D10)."""
    if ctx.scene_id is None:
        raise ToolRefused(OPEN_FIRST, how_to_fix="Answer without a card and tell the person to open the scene and "
                                                 "ask again.")
    store, scene = tooling.scene_in_scope(ctx, scene_ref)
    if str(scene["id"]) != str(ctx.scene_id):
        raise ToolRefused(OTHER_SCENE.format(scene=tooling.scene_label(scene)),
                          how_to_fix="Do not stage it; set handoff_scene and handoff_request instead.")
    return store, scene


def coverage(ctx: RunContext, store: Any, scene: Row) -> Coverage:
    sid = str(scene["id"])
    canon = store.canon(tooling.production_of(ctx))
    people = [c for c in canon if str(c.get("kind") or "character") == "character" and c.get("id")]
    return Coverage.from_rows(scene, store.shots(sid), store.lines(sid), people)


def run(ctx: RunContext, scene_ref: str | None, ops: list[RowOp]) -> tuple[RowTrial, list[Row]]:
    """→ (the trial, the operations as the kernel was handed them)."""
    store, scene = scene_of(ctx, scene_ref)
    before = coverage(ctx, store, scene)
    if not before.clips:
        raise ToolRefused("This scene has no shots yet, so there is nothing to change.",
                          how_to_fix="Tell the person to plan the scene's shots first.")
    raw = [o.as_op() for o in ops]
    after = before.copy()
    result = parts.step("coverage_kernel", "logic").Kernel(after).apply(raw, by=BY)
    trial = RowTrial(scene, before, after, list(result.applied), list(result.rejected), list(result.notes),
                     before.fingerprint())
    trial.done = changes(before, after)
    return trial, raw


def view(ctx: RunContext, scene_ref: str | None) -> tuple[Row, str]:
    """The open scene's clips as the row kernel numbers them (blocks with their line codes, then one line per clip)."""
    store, scene = scene_of(ctx, scene_ref)
    return scene, coverage(ctx, store, scene).render(detail=False)
