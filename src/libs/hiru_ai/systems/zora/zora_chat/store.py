"""Saving Zora's work and the revisions behind undo (plan/2026-11-06e §4.7, Phase 5). Shared by a turn and an action.

    Saver.save(plan, …)        the plan through the planner's write path (`zora_save`), every kept shot keeps its id; a
                               plan someone changed since the turn read it is refused (optimistic check); a revision is
                               written for undo, the oldest dropped past the kept window
    Saver.restore(kind)        undo or redo: the target revision's stored plan written back, itself a revision
    Saver.stack()              the revisions replayed (None: the database has no table yet; Zora runs without undo)

A revision write that fails never fails the save: the edit stands and the panel says undo is not available.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from hiru_ai.core.context import RunContext
from hiru_ai.steps.zora.zora_save import logic as save_logic
from hiru_ai.steps.zora.zora_save import step as save_step
from hiru_ai.systems.zora.zora_chat.scene import World, stored_of

_log = logging.getLogger(__name__)
Row = dict[str, Any]
CHANGED_MEANWHILE = ("Someone changed this scene's plan while I was working (a re-plan or another edit). Nothing was "
                     "saved; ask again and I will work from the new plan.")
NO_UNDO = "Undo is not available yet: the database has no plan revisions table (schema v14)."


@dataclass
class Saved:
    ok: bool
    reason: str = ""
    revision: int = 0
    rows: list[Row] | None = None


class Saver:
    def __init__(self, ctx: RunContext, world: World, *, actor_user_id: UUID | None, kept: int) -> None:
        self.ctx, self.world, self.actor, self.kept = ctx, world, actor_user_id, kept
        self.scenes, self.director = ctx.need("scenes"), ctx.need("director")
        self.revisions = ctx.ports.revisions
        # What the scene row held, not the plan in use: an adopted scene's plan is built from its shots and the row
        # holds none until the first save, so "changed meanwhile" compares the row with the row.
        self.read_print = save_logic.fingerprint(stored_of(world.scene_row))

    # ── the revisions ──────────────────────────────────────────────────────────────────────────────────

    def stack(self) -> save_logic.Stack | None:
        if self.revisions is None:
            return None
        try:
            return save_logic.Stack.of(self.revisions.revisions(self.world.scene_row["id"]))
        except Exception:
            _log.info("no plan revisions (the table is missing or unreadable); running without undo", exc_info=True)
            return None

    def _add(self, row: Row) -> bool:
        assert self.revisions is not None
        try:
            self.revisions.add_revision({**row, "production_id": str(self.world.scene_row["production_id"])})
            rows = self.revisions.revisions(self.world.scene_row["id"])
            gone = save_logic.prune(rows, self.kept)
            if gone:
                self.revisions.drop_revisions(self.world.scene_row["id"], gone)
            return True
        except Exception:
            _log.warning("a plan revision could not be written; the edit stands without undo", exc_info=True)
            return False

    def _base(self, stack: save_logic.Stack) -> save_logic.Stack:
        """Make sure the plan as the turn read it is a revision (the base the first undo returns to)."""
        if stack.current(self.world.stored):
            return stack
        row = save_logic.revision(str(self.world.scene_row["id"]), stack.next_revision, "base", self.world.stored,
                                  save_logic.ids_by_number(self.world.shot_rows), made_by=str(self.actor or ""))
        if self._add(row):
            return self.stack() or stack
        return stack

    # ── saving ────────────────────────────────────────────────────────────────────────────────────────

    def _changed_meanwhile(self) -> bool:
        now = self.director.scene(self.world.scene_row["production_id"], self.world.scene_row["id"])
        return save_logic.fingerprint(stored_of(now)) != self.read_print

    def save(self, plan: Row, *, handles: list[str], mended: list[str], problems: list[Row], measures: list[Row],
             person: Row, kind: str = "turn", message_id: str = "") -> Saved:
        w = self.world
        if self._changed_meanwhile():
            return Saved(False, CHANGED_MEANWHILE)
        out = save_step.run({"scene": w.scene_row, "lines": w.lines, "canon": w.canon, "production": w.production,
                             "stored": w.stored, "plan": plan, "mended": mended, "problems": problems,
                             "measures": measures, "person": person,
                             "old_ids": save_logic.ids_by_number(w.shot_rows), "handles": handles})
        if "refused" in out:
            return Saved(False, str(out["refused"]))
        stack = self.stack()
        if stack is not None:
            stack = self._base(stack)
        self.scenes.save_plan(w.scene_row["id"], out["shots"], out["removed"], out["lines"], out["fields"])
        self._advance(out["fields"]["jonathan"], out["shots"])
        number = 0
        if stack is not None:
            number = stack.next_revision
            row = save_logic.revision(str(w.scene_row["id"]), number, kind, out["fields"]["jonathan"],
                                      save_logic.ids_by_number(out["shots"]), made_by=str(self.actor or ""),
                                      message_id=message_id)
            number = number if self._add(row) else 0
        self._audit(kind, number)
        return Saved(True, revision=number, rows=out["shots"])

    def _advance(self, stored: Row, shots: list[Row]) -> None:
        """What a later save in the same turn or action reads as "the plan now"."""
        self.world.stored = stored
        self.world.scene_row = {**self.world.scene_row, "jonathan": stored}
        self.world.shot_rows = shots
        self.read_print = save_logic.fingerprint(stored)

    def restore(self, kind: str) -> Saved:
        """Undo or redo. The target revision's stored plan is written back through the planner's write path."""
        stack = self.stack()
        if stack is None:
            return Saved(False, NO_UNDO)
        if not stack.current(self.world.stored):
            return Saved(False, "The plan changed outside the chat since the last change I made (a re-plan), so "
                                "there is nothing to " + kind + " here.")
        target = stack.target(kind)
        if target is None:
            return Saved(False, "There is nothing to " + kind + ".")
        w = self.world
        stored = dict(target["stored"])
        out = save_step.write_rows(w.scene_row, w.lines, stored, w.canon, w.production)
        if "refused" in out:
            return Saved(False, str(out["refused"]))
        ids = [str(i) for i in target.get("shot_ids") or []]
        handles = [f"h{i}" for i in range(1, len(ids) + 1)]
        shots, lines, _ = save_logic.keep_ids(out["shots"], out["lines"], ids, handles)
        keep = {str(s["id"]) for s in shots}
        removed = [str(r["id"]) for r in w.shot_rows if str(r["id"]) not in keep]
        self.scenes.save_plan(w.scene_row["id"], shots, removed, lines, out["fields"])
        self._advance(out["fields"]["jonathan"], shots)
        number = stack.next_revision
        row = save_logic.revision(str(w.scene_row["id"]), number, kind, out["fields"]["jonathan"],
                                  save_logic.ids_by_number(shots), made_by=str(self.actor or ""),
                                  restores=int(target["revision"]))
        number = number if self._add(row) else 0
        self._audit(kind, number)
        return Saved(True, revision=number, rows=shots)

    def _audit(self, kind: str, number: int) -> None:
        try:
            self.director.audit({"production_id": str(self.world.scene_row["production_id"]),
                                 "actor_user_id": str(self.actor) if self.actor else None, "actor_agent": "zora_chat",
                                 "action": f"scene.zora_{kind}", "entity": "scene",
                                 "entity_id": str(self.world.scene_row["id"]), "diff": {"revision": number}})
        except Exception:
            _log.warning("audit row not written", exc_info=True)
