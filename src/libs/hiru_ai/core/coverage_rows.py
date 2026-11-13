"""The open scene's shot rows read as coverage, and saved back in place with revisions behind undo (plan/2026-11-13
§3.1, §3.5). Shared by Zora (a turn, a click) and Sable (a change card's Accept, phase 8): planner-free and chat-free.

    read(ctx, production_id, scene_id)  -> World | str   the scene, its rows, lines and canon, as coverage (or the
                                                         sentence to say when there is none)
    Saver.save(after, kind)    the changed clips written back (`scenes.save_plan`): ids kept, `number` renumbered
                               in row order, `version + 1` on every touched clip (its prompt, frame and video read as
                               out of date), a new clip with a fresh id and the scene's planner value; lines rebound; a
                               clip whose camera design changed is finished the way the planners finish theirs. Refused
                               when the rows changed since they were read (optimistic check). A revision follows
    Saver.restore(kind)        undo or redo: the target revision's rows written back, itself a revision
    Saver.stack()              the revisions replayed (None: the database has no table; the chat runs without undo)

A revision row is `{scene_id, revision, kind, restores, stored, shot_ids, made_by, message_id}`; `stored` is
`{"rows": [the scene's clip rows as written], "lines": [{id, shot_id}]}`. `kind` is `base` (the rows before the first
change), `turn`, `use` (an Accept, a "Use this", the silent-shot fix, a Sable card), `undo` or `redo`. A revision
written before plan/2026-11-13 holds a planner's JSON and no rows: the stack starts after it (D-C). Never written
here: a planner's JSON on the scene row, or the `planner` of an existing clip.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from contracts.coverage.scene import Coverage
from hiru_ai.core import parts
from hiru_ai.core.context import RunContext

_log = logging.getLogger(__name__)
Row = dict[str, Any]
KEPT = 30
CHANGES = frozenset({"turn", "use", "base"})
CHANGED_MEANWHILE = ("Someone changed this scene's shots while I was working (a re-plan or another edit). Nothing was "
                     "saved; ask again and I will work from the shots as they are now.")
NO_UNDO = "Undo is not available: the database has no plan revisions table."
BEFORE_ROWS = ("The earlier changes were made before I edited the shot rows directly, so I can't step back past this "
               "point.")
NO_SHOTS = "This scene has no shots yet. Plan its shots first."
GONE = "This scene is no longer available."


# ── the scene as coverage ─────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class World:
    production: Row
    scene_row: Row
    shot_rows: list[Row]
    lines: list[Row]
    canon: list[Row]
    cov: Coverage

    @property
    def characters(self) -> list[Row]:
        return characters_of(self.canon)

    def place(self) -> str:
        return str(self.scene_row.get("heading") or "")

    def people(self) -> list[str]:
        return sorted({ln.speaker for ln in self.cov.lines.values() if ln.speaker})


def characters_of(canon: list[Row]) -> list[Row]:
    return [c for c in canon if str(c.get("kind") or "character") == "character" and c.get("id")]


def coverage_of(scene_row: Row, shot_rows: list[Row], lines: list[Row], canon: list[Row]) -> Coverage:
    return Coverage.from_rows(scene_row, shot_rows, lines, characters_of(canon))


def read(ctx: RunContext, production_id: UUID, scene_id: UUID, *, no_shots: str = NO_SHOTS,
         gone: str = GONE) -> World | str:
    """The world of one turn or one click, or the sentence to say when there is none."""
    scenes, director = ctx.need("scenes"), ctx.need("director")
    production = scenes.production(production_id)
    row = director.scene(production_id, scene_id)
    if production is None or row is None:
        return gone
    shot_rows = scenes.shots(scene_id)
    if not shot_rows:
        return no_shots
    lines = scenes.lines(scene_id)
    canon = scenes.canon(production_id)
    return World(production=production, scene_row=row, shot_rows=shot_rows, lines=lines, canon=canon,
                 cov=coverage_of(row, shot_rows, lines, canon))


def reread(ctx: RunContext, world: World) -> Coverage:
    """The scene's rows as they are NOW (the optimistic check before a save)."""
    scenes = ctx.need("scenes")
    sid = world.scene_row["id"]
    return coverage_of(world.scene_row, scenes.shots(sid), scenes.lines(sid), world.canon)


# ── the revisions ─────────────────────────────────────────────────────────────────────────────────────────────────


def _num(v: Any) -> Any:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return v


def rows_print(rows: list[Row], lines: list[Row]) -> str:
    """A short hash of a scene's clips and line bindings, from the columns Zora writes (types normalised, so a row read
    back from the database prints as the row written)."""
    def one(r: Row) -> list[Any]:
        intent: Row = r["intent"] if isinstance(r.get("intent"), dict) else {}
        card: Row = r["card"] if isinstance(r.get("card"), dict) else {}
        return [str(r.get("id")), _num(r.get("number")), str(r.get("framing")), _num(r.get("duration_s")),
                str(r.get("sound_mode")), str(r.get("camera_link")), _num(r.get("block_start")),
                _num(r.get("block_end")), str(intent.get("purpose") or ""), str(intent.get("what_we_see") or ""),
                json.dumps(r.get("ir") or {}, sort_keys=True, default=str),
                json.dumps(card.get("sound") or {}, sort_keys=True, default=str)]

    state = [one(r) for r in sorted(rows, key=lambda r: _num(r.get("number")) or 0)]
    state.append(sorted([str(ln.get("id")), str(ln.get("shot_id") or "")] for ln in lines))
    return hashlib.sha256(json.dumps(state, default=str).encode()).hexdigest()[:16]


def _has_rows(row: Row) -> bool:
    stored = row.get("stored")
    return isinstance(stored, dict) and isinstance(stored.get("rows"), list)


@dataclass
class Stack:
    """The revisions of one scene, replayed: `done[-1]` is the state now, `done[-2]` what undo brings back, `undone[-1]`
    what redo brings back. Only revisions that hold rows count; `older` says a planner's revision came before them."""

    rows: dict[int, Row] = field(default_factory=dict)
    done: list[int] = field(default_factory=list)
    undone: list[int] = field(default_factory=list)
    older: bool = False
    top: int = 0

    @classmethod
    def of(cls, rows: list[Row]) -> Stack:
        usable = [r for r in rows if _has_rows(r)]
        st = cls(rows={int(r["revision"]): r for r in usable}, older=len(usable) < len(rows),
                 top=max((int(r["revision"]) for r in rows), default=0))
        for r in sorted(usable, key=lambda r: int(r["revision"])):
            n, kind = int(r["revision"]), str(r.get("kind") or "turn")
            if kind in CHANGES or not st.done:
                st.done.append(n)
                st.undone = []
            elif kind == "undo" and len(st.done) > 1:
                st.undone.append(st.done.pop())
            elif kind == "redo" and st.undone:
                st.done.append(st.undone.pop())
        return st

    @property
    def head(self) -> Row | None:
        return self.rows.get(self.done[-1]) if self.done else None

    @property
    def next_revision(self) -> int:
        return self.top + 1

    def can_undo(self) -> bool:
        return len(self.done) > 1

    def can_redo(self) -> bool:
        return bool(self.undone)

    def target(self, kind: str) -> Row | None:
        if kind == "undo":
            return self.rows.get(self.done[-2]) if self.can_undo() else None
        return self.rows.get(self.undone[-1]) if self.can_redo() else None

    def current(self, rows: list[Row], lines: list[Row]) -> bool:
        """Are the scene's rows the ones the head revision holds? (False: a re-plan or another edit landed outside the
        chat, and undo must not jump over it.)"""
        head = self.head
        if head is None:
            return False
        stored = head["stored"]
        return rows_print(stored["rows"], stored.get("lines") or []) == rows_print(rows, lines)


def revision(scene_id: str, number: int, kind: str, rows: list[Row], lines: list[Row], *, made_by: str = "",
             message_id: str = "", restores: int | None = None) -> Row:
    bound = [{"id": str(ln["id"]), "shot_id": ln.get("shot_id")} for ln in lines]
    ordered = sorted(rows, key=lambda r: _num(r.get("number")) or 0)
    return {"scene_id": scene_id, "revision": number, "kind": kind, "restores": restores,
            "stored": {"rows": copy.deepcopy(ordered), "lines": bound},
            "shot_ids": [str(r["id"]) for r in ordered], "made_by": made_by or None, "message_id": message_id or None}


def prune(rows: list[Row], keep: int = KEPT) -> list[int]:
    numbers = sorted(int(r["revision"]) for r in rows)
    return numbers[:-keep] if len(numbers) > keep else []


# ── rows out of a coverage ─────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Plan:
    """What one save writes: the rows to upsert, the ids to delete, the lines to rebind, and every row after it."""

    upsert: list[Row]
    removed: list[str]
    lines: list[Row]
    rows: list[Row]
    all_lines: list[Row]
    designs: list[str]  # ids whose camera design changed (finished before the save)
    touched: list[str]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def rows_for(before: Coverage, after: Coverage, *, planner: str, now: str = "") -> Plan:
    """The rows a save writes, from the coverage as read and the coverage after the edit (they share handles)."""
    now = now or _now()
    for c in after.clips:  # a new clip gets its id now, so the lines it performs can name it
        if not c.row_id:
            c.row_id = str(uuid.uuid4())
    upsert, rows, touched, designs = [], [], [], []
    for n, c in enumerate(after.clips, start=1):
        old = before.clip(c.h)
        moved = old is not None and ({ln.lid for ln in before.performs(c.h)} != {ln.lid for ln in after.performs(c.h)})
        if old is None or old.content() != c.content() or moved:
            row = after.row_of(c, number=n, row_id=c.row_id, planner=planner, now=now)
            row["version"] = int(row.get("version") or 0) + 1
            row["updated_at"] = now
            upsert.append(row)
            touched.append(c.row_id)
            if old is None or json.dumps(old.ir, sort_keys=True, default=str) != json.dumps(c.ir, sort_keys=True,
                                                                                         default=str):
                if c.ir:
                    designs.append(c.row_id)
        else:
            row = dict(after.rows[c.row_id])
            if _num(row.get("number")) != n:
                row["number"] = n
                upsert.append(row)
        rows.append(row)
    removed = [c.row_id for c in before.clips if after.clip(c.h) is None and c.row_id]
    by_h = {c.h: c.row_id for c in after.clips}
    lines, all_lines = [], []
    for ln in after.lines.values():
        src = dict(after.line_rows[ln.row_id])
        shot_id = by_h.get(ln.by) if ln.by else None
        if str(src.get("shot_id") or "") != str(shot_id or ""):
            src["shot_id"] = shot_id
            lines.append(src)
        all_lines.append(src)
    bound = {str(r["id"]) for r in all_lines}
    all_lines += [dict(r) for i, r in after.line_rows.items() if i not in bound]  # a line no block names: untouched
    return Plan(upsert, removed, lines, rows, all_lines, designs, touched)


def finish_designs(world: World, plan: Plan) -> None:
    """Each clip whose camera design changed is finished the way the planners finish theirs (`serialize.shots.finish`,
    reached by id) and given a design row. A clip that cannot be finished keeps the IR as written (logged)."""
    if not plan.designs:
        return
    try:
        model = parts.step("serialize", "model")
        shots_mod = parts.step("serialize", "shots")
        design = parts.step("serialize", "design")
        prod = model.production_input(world.production, world.canon, None)
        scene_in = model.scene_input(world.scene_row, plan.rows, plan.all_lines, world.canon, prod)
        want = set(plan.designs)
        for shot_in, row in zip(scene_in.shots, plan.rows, strict=True):
            if str(row["id"]) not in want:
                continue
            intent = row.get("intent") or {}
            entry = {**(row.get("ir") or {}), "rationale": str(intent.get("purpose") or "")}
            ir, rec, why = shots_mod.finish(entry, shot_in, scene_in, prod)
            row["ir"] = ir
            row["design"] = design.design_row(shot_in, ir, rec, why, "zora", list(intent.get("on_screen") or []), "")
    except Exception:
        _log.warning("a changed camera design could not be finished; it is saved as written", exc_info=True)


# ── the saver ─────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Saved:
    ok: bool
    reason: str = ""
    revision: int = 0
    rows: list[Row] | None = None


class Saver:
    def __init__(self, ctx: RunContext, world: World, *, actor_user_id: UUID | None, kept: int = KEPT,
                 chat: str = "zora") -> None:
        self.ctx, self.world, self.actor, self.kept, self.chat = ctx, world, actor_user_id, kept, chat
        self.scenes, self.director = ctx.need("scenes"), ctx.need("director")
        self.revisions = ctx.ports.revisions
        self.read_print = world.cov.fingerprint()

    @property
    def scene_id(self) -> str:
        return str(self.world.scene_row["id"])

    def planner(self) -> str:
        """The scene's existing planner value (the column's check list), for a new clip ("" = its neighbour's)."""
        return next((str(r["planner"]) for r in self.world.shot_rows if r.get("planner")), "")

    def stack(self) -> Stack | None:
        if self.revisions is None:
            return None
        try:
            return Stack.of(self.revisions.revisions(self.scene_id))
        except Exception:
            _log.info("no plan revisions (the table is missing or unreadable); running without undo", exc_info=True)
            return None

    def _add(self, row: Row) -> bool:
        assert self.revisions is not None
        try:
            self.revisions.add_revision({**row, "production_id": str(self.world.scene_row["production_id"])})
            gone = prune(self.revisions.revisions(self.scene_id), self.kept)
            if gone:
                self.revisions.drop_revisions(self.scene_id, gone)
            return True
        except Exception:
            _log.warning("a plan revision could not be written; the edit stands without undo", exc_info=True)
            return False

    def _base(self, stack: Stack) -> Stack:
        """The rows as the turn read them become a revision (what the first undo returns to)."""
        w = self.world
        if stack.current(w.shot_rows, w.lines):
            return stack
        if self._add(revision(self.scene_id, stack.next_revision, "base", w.shot_rows, w.lines,
                              made_by=str(self.actor or ""))):
            return self.stack() or stack
        return stack

    def changed_meanwhile(self) -> bool:
        sid = self.scene_id
        now = coverage_of(self.world.scene_row, self.scenes.shots(sid), self.scenes.lines(sid), self.world.canon)
        return now.fingerprint() != self.read_print

    def save(self, after: Coverage, *, kind: str = "turn", message_id: str = "") -> Saved:
        if self.changed_meanwhile():
            return Saved(False, CHANGED_MEANWHILE)
        plan = rows_for(self.world.cov, after, planner=self.planner())
        finish_designs(self.world, plan)
        stack = self.stack()
        if stack is not None:
            stack = self._base(stack)
        self.scenes.save_plan(self.scene_id, plan.upsert, plan.removed, plan.lines, {"updated_at": _now()})
        number = self._revise(stack, kind, plan.rows, plan.all_lines, message_id=message_id)
        self._advance(plan.rows, plan.all_lines)
        self._audit(kind, number)
        return Saved(True, revision=number, rows=plan.rows)

    def _revise(self, stack: Stack | None, kind: str, rows: list[Row], lines: list[Row], *, message_id: str = "",
                restores: int | None = None) -> int:
        if stack is None:
            return 0
        number = stack.next_revision
        row = revision(self.scene_id, number, kind, rows, lines, made_by=str(self.actor or ""), message_id=message_id,
                       restores=restores)
        return number if self._add(row) else 0

    def _advance(self, rows: list[Row], lines: list[Row]) -> None:
        """What a later save in the same turn or click reads as "the rows now"."""
        w = self.world
        w.shot_rows, w.lines = [dict(r) for r in rows], [dict(ln) for ln in lines]
        w.cov = coverage_of(w.scene_row, w.shot_rows, w.lines, w.canon)
        self.read_print = w.cov.fingerprint()

    def restore(self, kind: str) -> Saved:
        """Undo or redo: the target revision's rows written back."""
        stack = self.stack()
        if stack is None:
            return Saved(False, NO_UNDO)
        w = self.world
        if not stack.done:
            return Saved(False, BEFORE_ROWS if stack.older and kind == "undo" else f"There is nothing to {kind}.")
        if not stack.current(w.shot_rows, w.lines):
            return Saved(False, "The shots changed outside the chat since the last change I made (a re-plan), so "
                                f"there is nothing to {kind} here.")
        target = stack.target(kind)
        if target is None:
            if kind == "undo" and stack.older:
                return Saved(False, BEFORE_ROWS)
            return Saved(False, f"There is nothing to {kind}.")
        stored = target["stored"]
        now_rows = {str(r["id"]): r for r in w.shot_rows}
        now = _now()
        rows, upsert = [], []
        for r in stored["rows"]:
            row = copy.deepcopy(r)
            cur = now_rows.get(str(row["id"]))
            if cur is None or rows_print([cur], []) != rows_print([row], []):
                row["version"] = int((cur or row).get("version") or 0) + 1
                row["updated_at"] = now
                upsert.append(row)
            rows.append(row)
        keep = {str(r["id"]) for r in rows}
        removed = [i for i in now_rows if i not in keep]
        binding = {str(b["id"]): b.get("shot_id") for b in stored.get("lines") or []}
        lines, all_lines = [], []
        for ln in w.lines:
            row = dict(ln)
            if str(row["id"]) in binding and str(row.get("shot_id") or "") != str(binding[str(row["id"])] or ""):
                row["shot_id"] = binding[str(row["id"])]
                lines.append(row)
            all_lines.append(row)
        self.scenes.save_plan(self.scene_id, upsert, removed, lines, {"updated_at": now})
        number = self._revise(stack, kind, rows, all_lines, restores=int(target["revision"]))
        self._advance(rows, all_lines)
        self._audit(kind, number)
        return Saved(True, revision=number, rows=rows)

    def _audit(self, kind: str, number: int) -> None:
        try:
            self.director.audit({"production_id": str(self.world.scene_row["production_id"]),
                                 "actor_user_id": str(self.actor) if self.actor else None,
                                 "actor_agent": f"{self.chat}_chat", "action": f"scene.{self.chat}_{kind}",
                                 "entity": "scene", "entity_id": self.scene_id,
                                 "diff": {"revision": number}})
        except Exception:
            _log.warning("audit row not written", exc_info=True)
