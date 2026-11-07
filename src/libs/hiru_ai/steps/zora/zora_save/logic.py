"""Zora's save, undo and redo (plan/2026-11-06e §4.7, Phase 5). Pure rows in, rows out; the system saves them.

    stored_after(stored, plan, ...)   the scene's new `scenes.<planner>` JSON: the edited plan, what code mended, what
                                      is left, the craft measures, the end state and the person's locks. The rest of
                                      what the planner keeps (its link, start, removed additions, line ids,
                                      `previous`) is left exactly as it was
    keep_ids(new_rows, old_ids, …)    the planner's write path makes new shot ids; a shot that was there before the
                                      turn keeps its id (frames and prompts hang off it), matched by kernel handle
    fingerprint(stored)               what the turn read, so a save over a plan someone changed meanwhile is refused
    Stack.of(rows)                    the revisions replayed: the state now, what undo and redo would restore

A revision row is `{scene_id, revision, kind, restores, stored, shot_ids, made_by, message_id}`: `stored` is the WHOLE
`scenes.<planner>` JSON after the change and `shot_ids` the shot id of each number, so a restore re-runs the planner's
write path on the stored plan and gives the shots their ids back. `kind` is `base` (the plan before the first Zora
change), `turn`, `use` (a proposal), `undo` or `redo`; `restores` names the revision an undo or a redo brought back.
Redo is the undo of an undo: a new change after an undo clears what could be redone.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

Row = dict[str, Any]
KEPT = 30  # revisions per scene (D4)
CHANGES = frozenset({"turn", "use", "base"})


def fingerprint(stored: Row | None) -> str:
    """A short hash of the stored plan as the turn read it ("" for none)."""
    if not stored:
        return ""
    body = json.dumps(stored.get("plan") or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def stored_after(stored: Row, plan: Row, *, mended: list[str], problems: list[Row], measures: list[Row],
                 person: Row) -> Row:
    """The planner's stored JSON with Zora's edit in it. `problems` are the planner's own, as its check returned them
    (`{code, sentence, shots, fix, key}`), all of them: reported, never blocking."""
    out = copy.deepcopy(stored)
    out["plan"] = copy.deepcopy(plan)
    out["mended"] = list(dict.fromkeys(mended))
    out["problems"] = [{k: p.get(k) for k in ("code", "sentence", "shots", "fix", "key") if k in p} for p in problems]
    out["measures"] = list(measures)
    out["end_state"] = copy.deepcopy(plan.get("end_state"))
    out["person"] = {"locked": list(person.get("locked") or []), "settled": list(person.get("settled") or [])}
    return out


def keep_ids(rows: list[Row], lines: list[Row], old_ids: list[str], handles: list[str]) -> tuple[list[Row], list[Row],
                                                                                               list[str]]:
    """Give each new shot row the id of the shot it was before the turn. `old_ids[i]` is the id of the shot that was
    number i+1 when the turn began (its handle `h{i+1}`); `handles[n-1]` is the handle of shot n after it. A new shot
    keeps the planner's fresh id. → (shots, lines with their shot ids remapped, the old ids no shot keeps)."""
    by_handle = {f"h{i}": sid for i, sid in enumerate(old_ids, start=1) if sid}
    remap: dict[str, str] = {}
    used: set[str] = set()
    out = []
    for row in rows:
        n = int(row["number"])
        handle = handles[n - 1] if 1 <= n <= len(handles) else ""
        old = by_handle.get(handle)
        new = dict(row)
        if old and old not in used:
            remap[str(row["id"])] = old
            new["id"] = old
            used.add(old)
        out.append(new)
    bound = [{**ln, "shot_id": remap.get(str(ln.get("shot_id")), ln.get("shot_id"))} for ln in lines]
    gone = [sid for sid in old_ids if sid and sid not in used]
    return out, bound, gone


def ids_by_number(rows: list[Row]) -> list[str]:
    """The shot id of each number, in order (index 0 = shot 1)."""
    return [str(r["id"]) for r in sorted(rows, key=lambda r: int(r.get("number") or 0))]


@dataclass
class Stack:
    """The revisions of one scene, replayed: `done[-1]` is the state now, `done[-2]` what undo brings back, `undone[-1]`
    what redo brings back. Rows older than the kept window are gone; the oldest one kept is the base."""

    rows: dict[int, Row] = field(default_factory=dict)
    done: list[int] = field(default_factory=list)
    undone: list[int] = field(default_factory=list)

    @classmethod
    def of(cls, rows: list[Row]) -> Stack:
        st = cls(rows={int(r["revision"]): r for r in rows})
        for r in sorted(rows, key=lambda r: int(r["revision"])):
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
        return max(self.rows, default=0) + 1

    def can_undo(self) -> bool:
        return len(self.done) > 1

    def can_redo(self) -> bool:
        return bool(self.undone)

    def target(self, kind: str) -> Row | None:
        """The revision an undo (or a redo) restores; None when there is nothing to go to."""
        if kind == "undo":
            return self.rows.get(self.done[-2]) if self.can_undo() else None
        return self.rows.get(self.undone[-1]) if self.can_redo() else None

    def current(self, stored: Row | None) -> bool:
        """Is the scene's plan the one the head revision holds? (False: a re-plan or another edit landed outside
        the chat, and undo must not jump over it.)"""
        head = self.head
        return head is not None and fingerprint(head.get("stored")) == fingerprint(stored)


def revision(scene_id: str, number: int, kind: str, stored: Row, shot_ids: list[str], *, made_by: str = "",
             message_id: str = "", restores: int | None = None) -> Row:
    return {"scene_id": scene_id, "revision": number, "kind": kind, "restores": restores, "stored": stored,
            "shot_ids": list(shot_ids), "made_by": made_by or None, "message_id": message_id or None}


def prune(rows: list[Row], keep: int = KEPT) -> list[int]:
    """The revision numbers to delete so that `keep` remain."""
    numbers = sorted(int(r["revision"]) for r in rows)
    return numbers[:-keep] if len(numbers) > keep else []
