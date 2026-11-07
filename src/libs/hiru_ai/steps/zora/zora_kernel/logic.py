"""Zora's kernel (plan/2026-11-06e §4.2): applies operations to one scene's stored plan and knows what each changed.

Ported from PromptMotion Nova Studio's `PlanKernel` (studio/ops.py) and changed for a Hiru plan. The properties it
guarantees, each pinned by `tests/zora/test_kernel.py`:

  1. Addressing is stable within a batch. Operations name shots (and arc beats) by their number AT THE START of the
     batch; the kernel resolves each number to a handle once and renumbers once at the end. Two inserts in one batch do
     not shift each other, and a task's numbers (post-op) are read against the exported plan.
  2. Undo is exact: every applied operation keeps a snapshot, and `undo(result)` restores the plan byte for byte.
  3. A bad operation never corrupts the plan: after each one the whole plan is re-validated (the planner's wire shape in
     code, plus the planner's own validation when the step passes it); a failure rolls that one operation back. Only a
     fault the operation ADDS counts: what the plan already had when it was loaded (S07 naming a line the script has
     since moved) is `known`, keyed by the shot's handle so renumbering does not make it look new, and is reported by
     `already()`, never a reason to refuse an edit elsewhere.
  4. Removals land whole or not at all (Nova W3 `_all_or_nothing`): if one removal in a batch is refused, none lands.
  5. A lock is the person saying "not this": the author may not write a locked path; the conductor (the person's own
     words) and the person may, and what they set becomes locked.
  6. No path writes a line's words: lines are bound to shots by code, from the blocks the shot shows.

The kernel never calls a model and never makes a creative decision. Authored text it cannot derive (a new shot's `why`
and picture, a merged shot's one picture) is left EMPTY, which is what tells the dependency graph the author has to
write it.
"""
from __future__ import annotations

import copy
import re
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

from contracts.zora import ops as O
from contracts.zora.doc import Person, ZoraDoc, shape_errors

Validate = Callable[[dict[str, Any]], list[str]]
Row = dict[str, Any]
# The size an added shot starts with, by what it is for (a starting point the author may change).
SIZE_FOR = {"reaction": "CU", "listener": "MCU", "insert_detail": "INSERT", "hands": "INSERT", "plant": "INSERT",
            "pov": "POV", "atmosphere": "WIDE", "empty_frame": "WIDE", "baseline": "WIDE", "transition": "WIDE",
            "implied_action": "MS", "move": "MS", "hold": "MS"}
_SHOT_CODE = re.compile(r"\bS(\d+)\b")  # a shot named in a fault's sentence (`O.code`: S07)


@dataclass
class Change:
    """What one applied operation did, in the terms the dependency graph reasons about. `handles` are kernel handles
    (stable across renumbering), never shot numbers."""

    kind: str  # the op name, or "lock"
    handles: tuple[str, ...] = ()
    field: str = ""
    by: str = ""
    detail: dict[str, Any] = dc_field(default_factory=dict)


@dataclass
class Result:
    applied: list[Row] = dc_field(default_factory=list)
    rejected: list[Row] = dc_field(default_factory=list)  # {"op", "reason", "by"}
    staged: list[Row] = dc_field(default_factory=list)  # script / translation / marks: a card for the person
    changes: list[Change] = dc_field(default_factory=list)
    undo: list[tuple[Any, ...]] = dc_field(default_factory=list)

    def extend(self, other: Result) -> None:
        self.applied += other.applied
        self.rejected += other.rejected
        self.staged += other.staged
        self.changes += other.changes
        self.undo += other.undo


class ZoraKernel:
    """Holds one plan with a handle on every shot (`_h`: h1.. as loaded, n1.. for new ones) and every arc beat."""

    def __init__(self, doc: ZoraDoc, *, validate: Validate | None = None) -> None:
        self.scene: Row = doc.scene
        self.plan: Row = copy.deepcopy(doc.plan)
        self.validate = validate
        self._new = 0
        for i, s in enumerate(self.plan.get("shots") or [], start=1):
            s["_h"] = f"h{i}"
        for i, a in enumerate(self.plan["treatment"].get("arc") or [], start=1):
            a["_h"] = f"a{i}"
        by_n = {s["n"]: s["_h"] for s in self.plan["shots"]}
        for a in self.plan.get("added") or []:
            a["shot"] = by_n.get(a["shot"], f"?{a['shot']}")
        self.locked: list[str] = [self._to_handles(p) for p in doc.person.locked]
        self.settled: list[str] = [self._to_handles(p) for p in doc.person.settled]
        self.pinned: set[str] = set()  # shots whose take a person set this turn: the mend may lengthen, never shorten
        self.known: set[str] = {self._fault_key(e) for e in self._faults()}  # what the plan had before any edit

    # ── faults: what makes the plan not read ─────────────────────────────────────────────────────────────

    def _faults(self) -> list[str]:
        """Every reason the plan as it stands would not read: the wire shape against the scene, then the planner's own
        validation (both always, so a fault already in the plan does not hide a new one behind it)."""
        plan = self.export()
        errors = shape_errors(plan, self.scene)
        if self.validate is not None:
            errors += self.validate(plan)
        return errors

    def _fault_key(self, sentence: str) -> str:
        """A fault with its shots named by handle (S07 → #h7), so it is the same fault after shots are renumbered."""
        handles = self.handles()
        return _SHOT_CODE.sub(lambda m: f"#{handles[int(m[1]) - 1]}" if 1 <= int(m[1]) <= len(handles) else m[0],
                              sentence)

    def new_faults(self) -> list[str]:
        """The faults the edits so far ADDED: what refuses an operation."""
        return [e for e in self._faults() if self._fault_key(e) not in self.known]

    def already(self) -> list[str]:
        """The faults the plan had when it was loaded and still has, in today's shot numbers: reported to the person
        once (they block nothing; a re-plan, or the person, clears them)."""
        return list(dict.fromkeys(e for e in self._faults() if self._fault_key(e) in self.known))

    # ── reading ───────────────────────────────────────────────────────────────────────────────

    @property
    def shots(self) -> list[Row]:
        return list(self.plan["shots"])

    def handles(self) -> list[str]:
        return [s["_h"] for s in self.plan["shots"]]

    def index_of(self, handle: str) -> int:
        for i, s in enumerate(self.plan["shots"]):
            if s["_h"] == handle:
                return i
        raise O.OpError("that shot no longer exists")

    def number_of(self, handle: str) -> int | None:
        try:
            return self.index_of(handle) + 1
        except O.OpError:
            return None

    def shot(self, handle: str) -> Row:
        return self.plan["shots"][self.index_of(handle)]

    def code_of(self, handle: str) -> str:
        n = self.number_of(handle)
        return O.code(n) if n else "a removed shot"

    def sequence_of(self, handle: str) -> str:
        try:
            return str(self.shot(handle).get("sequence") or "")
        except O.OpError:
            return ""

    def shots_in(self, sequence: str) -> list[str]:
        return [s["_h"] for s in self.plan["shots"] if s.get("sequence") == sequence]

    def line_ids(self) -> dict[int, str]:
        return {int(b["index"]): str(b["line_id"]) for b in self.scene.get("blocks") or []
                if b.get("kind") == "dialogue" and b.get("line_id")}

    def block_indices(self) -> set[int]:
        return {int(b["index"]) for b in self.scene.get("blocks") or []}

    def _to_handles(self, path: str) -> str:
        """`S03.lens` → `#h3.lens` (a lock follows its shot when shots are renumbered)."""
        head, dot, rest = path.partition(".")
        try:
            n = O.shot_number(head) if head[:1] in "Ss" else None
        except O.OpError:
            n = None
        if n is None:
            return path
        shots = self.plan["shots"]
        return f"#{shots[n - 1]['_h']}{dot}{rest}" if 1 <= n <= len(shots) else path

    def _to_numbers(self, path: str) -> str:
        if not path.startswith("#"):
            return path
        handle, dot, rest = path[1:].partition(".")
        n = self.number_of(handle)
        return f"{O.code(n)}{dot}{rest}" if n else ""

    # ── the plan out ──────────────────────────────────────────────────────────────────────────

    def export(self, *, handles: bool = False) -> Row:
        """The plan: shots numbered 1.. in order, additions following their shots, sequences' spans written again from
        the shots, and every handle taken out (kept with `handles=True`, for a diff paired by handle)."""
        out = copy.deepcopy(self.plan)
        number = {s["_h"]: i for i, s in enumerate(out["shots"], start=1)}
        for s in out["shots"]:
            s["n"] = number[s["_h"]]
            if not handles:
                del s["_h"]
        for a in out["treatment"].get("arc") or []:
            if not handles:
                a.pop("_h", None)
        out["added"] = sorted(({**a, "shot": number[a["shot"]]} for a in out.get("added") or [] if a["shot"] in number),
                              key=lambda a: a["shot"])
        for q in out["sequences"]:
            mine = [s["n"] for s in out["shots"] if s.get("sequence") == q["id"]]
            if mine:
                q["shots"] = {"first": min(mine), "last": max(mine)}
        return out

    def person(self) -> Person:
        return Person(locked=[p for p in dict.fromkeys(self._to_numbers(x) for x in self.locked) if p],
                      settled=[p for p in dict.fromkeys(self._to_numbers(x) for x in self.settled) if p])

    def doc(self) -> ZoraDoc:
        return ZoraDoc(plan=self.export(), scene=self.scene, person=self.person())

    # ── applying ──────────────────────────────────────────────────────────────────────────────

    def _snapshot(self) -> tuple[Any, ...]:
        return ("all", copy.deepcopy(self.plan), list(self.locked), list(self.settled), set(self.pinned), self._new)

    def _restore(self, snap: tuple[Any, ...]) -> None:
        _, plan, locked, settled, pinned, new = snap
        self.plan, self.locked, self.settled, self.pinned, self._new = (copy.deepcopy(plan), list(locked),
                                                                       list(settled), set(pinned), new)

    def undo(self, result: Result) -> None:
        """Restore the plan to exactly what it was before `result`'s batch."""
        if result.undo:
            self._restore(result.undo[0])

    def apply(self, ops: list[Any], *, by: str = "conductor", allowed_ops: tuple[str, ...] | None = None) -> Result:
        """Apply a batch. Numbers are resolved against the plan as it stands NOW. Removals go last, as one group."""
        result = Result()
        addr = {i: s["_h"] for i, s in enumerate(self.plan["shots"], start=1)}
        arcs = {i: a["_h"] for i, a in enumerate(self.plan["treatment"].get("arc") or [], start=1)}
        self._chain: dict[str, str] = {}
        batch = [O.infer_op(op) for op in list(ops or [])[:O.MAX_OPS]]
        names = [str(op.get("op") or "").strip().lower() if isinstance(op, dict) else "" for op in batch]
        rest = [op for op, n in zip(batch, names, strict=True) if n not in O.REMOVALS]
        removals = [op for op, n in zip(batch, names, strict=True) if n in O.REMOVALS]
        for raw in rest:
            self._one(raw, addr, arcs, by, allowed_ops, result)
        if removals:
            before = self._snapshot()
            group = Result()
            for raw in removals:
                self._one(raw, addr, arcs, by, allowed_ops, group)
            if group.rejected and group.applied:  # whole or not at all
                self._restore(before)
                why = "; ".join(r["reason"] for r in group.rejected)
                result.rejected += group.rejected + [
                    {"op": a, "by": by, "reason": f"not applied: removals land whole or not at all ({why})"}
                    for a in group.applied]
            else:
                result.extend(group)
        return result

    def _one(self, raw: Any, addr: dict[int, str], arcs: dict[int, str], by: str,
             allowed_ops: tuple[str, ...] | None, result: Result) -> None:
        try:
            op = O.normalize_op(raw)
            name = op["op"]
            level, who = O.OPS[name]
            if by not in who:
                raise O.OpError(f"{_who(by)} may not use {name}" + (" (a person's own change, staged as a card)"
                                                                    if level in O.STAGED_LEVELS else ""))
            if allowed_ops is not None and name not in allowed_ops:
                raise O.OpError(f"{name} is outside this task")
            if level in O.STAGED_LEVELS:
                result.staged.append({**op, "by": by})
                return
            paths = self._addressed(op, addr)
            locked = next((p for p in paths if self._locked(p)), "") if by in O.CREATIVE else ""
            if locked:
                raise O.OpError(f"{self._to_numbers(locked) or locked} is locked: a person set it")
            snap = self._snapshot()
            try:
                normalized, changes = self._dispatch(op, addr, arcs, by)
                errors = self.new_faults()
                if errors:
                    raise O.OpError(f"the plan would not read ({errors[0]})")
            except O.OpError:
                self._restore(snap)
                raise
            if by in ("conductor", "person") and name in O.LOCKING:
                self.locked = list(dict.fromkeys([*self.locked, *paths]))
            for c in changes:
                c.by = by
            result.undo.append(snap)
            result.changes += changes
            result.applied.append({**normalized, "by": by})
        except O.OpError as exc:
            result.rejected.append({"op": raw, "reason": str(exc), "by": by})

    def _addressed(self, op: Row, addr: dict[int, str]) -> list[str]:
        """The paths an op writes, a shot named by its handle (the op's numbers are the batch's start), so a lock is
        checked on the right shot. A merge writes both its shots."""
        out = []
        for path in O.path_of(op).split("+"):
            head, dot, rest = path.partition(".")
            handle = addr.get(int(head[1:])) if head[:1] == "S" and head[1:].isdigit() else None
            out.append(f"#{handle}{dot}{rest}" if handle else path)
        return out

    def _locked(self, path: str) -> bool:
        return any(path == p or path.startswith(p + ".") for p in self.locked)

    def _resolve(self, addr: dict[int, str], value: Any, name: str = "shot") -> str:
        n = O.shot_number(value)
        handle = addr.get(n)
        if handle is None:
            raise O.OpError(f"there is no {O.code(n)}: the scene has {_range(len(addr))}" if name == "shot"
                            else f"there is no {O.code(n)} to put it after: the scene has {_range(len(addr))}")
        self.index_of(handle)  # raises if an earlier op of this batch removed it
        return handle

    def _dispatch(self, op: Row, addr: dict[int, str], arcs: dict[int, str], by: str) -> tuple[Row, list[Change]]:
        name = op["op"]
        handler: Callable[..., tuple[Row, list[Change]]] = getattr(self, "_op_" + name.replace(".", "_"))
        return handler(op, addr, arcs, by)

    # ── treatment ─────────────────────────────────────────────────────────────────────────────

    def _op_treatment_set(self, op: Row, addr: Any, arcs: Any, by: str) -> tuple[Row, list[Change]]:
        key = str(op.get("field") or "")
        if key not in O.TREATMENT_FIELDS:
            raise O.OpError(f"the treatment has no field {key!r} (it has {', '.join(O.TREATMENT_FIELDS)}; the arc, the "
                            "colour script and the sequences have their own operations)")
        value = O.text(op.get("value"), key)
        old = self.plan["treatment"][key]
        self.plan["treatment"][key] = value
        return ({"op": "treatment.set", "field": key, "value": value},
                [Change("treatment.set", (), key, detail={"old": old, "new": value})])

    def _arc(self, arcs: dict[int, str], value: Any) -> Row:
        n = O.whole(value, "the arc beat")
        handle = arcs.get(n)
        for a in self.plan["treatment"]["arc"]:
            if a.get("_h") == handle:
                return dict(a)
        raise O.OpError(f"there is no arc beat {n}: the arc has beats 1–{len(arcs)}" if arcs else "the arc is empty")

    def _span(self, op: Row, first: str, last: str, default: Row) -> Row:
        a = O.whole(op[first], first) if op.get(first) is not None else int(default["first"])
        b = O.whole(op[last], last) if op.get(last) is not None else int(default["last"])
        known = self.block_indices()
        if a > b or a not in known or b not in known:
            raise O.OpError(f"blocks b{a}–b{b} are not a run of this scene's blocks (it has b{min(known)}–"
                            f"b{max(known)})")
        return {"first": a, "last": b}

    def _op_arc_set(self, op: Row, addr: Any, arcs: dict[int, str], by: str) -> tuple[Row, list[Change]]:
        beat = self._arc(arcs, op.get("n"))
        entry = next(a for a in self.plan["treatment"]["arc"] if a["_h"] == beat["_h"])
        old = copy.deepcopy(entry)
        for key in O.ARC_FIELDS:
            if op.get(key) is not None:
                entry[key] = O.text(op[key], key)
        if op.get("first") is not None or op.get("last") is not None:
            entry["blocks"] = self._span(op, "first", "last", entry["blocks"])
        if entry == old:
            raise O.OpError("arc.set needs a beat, a feeling, or blocks first/last")
        return ({"op": "arc.set", "n": op.get("n"), **{k: entry[k] for k in ("beat", "feeling", "blocks")}},
                [Change("arc.set", (entry["_h"],), "arc", detail={"old": _plain(old), "new": _plain(entry)})])

    def _op_arc_add(self, op: Row, addr: Any, arcs: dict[int, str], by: str) -> tuple[Row, list[Change]]:
        after = O.whole(op.get("after", len(arcs)), "after")
        if not 0 <= after <= len(arcs):
            raise O.OpError(f"an arc beat goes after beat 0 (the start) to {len(arcs)}")
        beat = O.text(op.get("beat"), "beat")
        feeling = O.text(op.get("feeling", ""), "feeling")
        blocks = self._span(op, "first", "last", {"first": op.get("first"), "last": op.get("last")}) \
            if op.get("first") is not None else None
        if blocks is None:
            raise O.OpError("a new arc beat needs the blocks it spans (first and last)")
        self._new += 1
        handle = f"an{self._new}"
        entry: Row = {"beat": beat, "blocks": blocks, "feeling": feeling, "_h": handle}
        arc = self.plan["treatment"]["arc"]
        index = 0 if after == 0 else next(i for i, a in enumerate(arc) if a["_h"] == arcs[after]) + 1
        arc.insert(index, entry)
        return ({"op": "arc.add", "after": after, "beat": beat, "feeling": feeling, "blocks": blocks},
                [Change("arc.add", (handle,), "arc", detail={"new": _plain(entry)})])

    def _op_arc_remove(self, op: Row, addr: Any, arcs: dict[int, str], by: str) -> tuple[Row, list[Change]]:
        beat = self._arc(arcs, op.get("n"))
        arc = self.plan["treatment"]["arc"]
        if len(arc) <= 1:
            raise O.OpError("the arc needs at least one beat")
        arc[:] = [a for a in arc if a["_h"] != beat["_h"]]
        return ({"op": "arc.remove", "n": op.get("n"), "was": beat.get("beat", "")},
                [Change("arc.remove", (beat["_h"],), "arc", detail={"old": _plain(beat)})])

    def _op_colour_set(self, op: Row, addr: Any, arcs: Any, by: str) -> tuple[Row, list[Change]]:
        seq = self._sequence_id(op.get("sequence"))
        key = str(op.get("field") or "")
        if key not in O.COLOUR_FIELDS:
            raise O.OpError(f"a colour entry has no field {key!r} (it has {', '.join(O.COLOUR_FIELDS)})")
        value = O.text(op.get("value"), key)
        script = self.plan["treatment"]["colour_script"]
        entry = next((c for c in script if c.get("sequence") == seq), None)
        if entry is None:
            entry = {"sequence": seq, "palette": "", "light": "", "grade": ""}
            script.append(entry)
            script.sort(key=lambda c: self.plan_sequence_index(c["sequence"]))
        old = entry[key]
        entry[key] = value
        return ({"op": "colour.set", "sequence": seq, "field": key, "value": value},
                [Change("colour.set", tuple(self.shots_in(seq)), key, detail={"sequence": seq, "old": old,
                                                                             "new": value})])

    def plan_sequence_index(self, seq: str) -> int:
        ids = [q["id"] for q in self.plan["sequences"]]
        return ids.index(seq) if seq in ids else len(ids)

    # ── sequences ─────────────────────────────────────────────────────────────────────────────

    def _sequence_id(self, value: Any) -> str:
        wanted = str(value or "").strip().upper()
        ids = [str(q["id"]) for q in self.plan["sequences"]]
        if wanted not in ids:
            raise O.OpError(f"there is no sequence {value!r}: the scene has {', '.join(ids)}")
        return wanted

    def _sequence(self, seq: str) -> Row:
        return next(q for q in self.plan["sequences"] if q["id"] == seq)

    def _op_sequence_set(self, op: Row, addr: Any, arcs: Any, by: str) -> tuple[Row, list[Change]]:
        seq = self._sequence_id(op.get("id"))
        key = str(op.get("field") or "")
        if key not in O.SEQUENCE_FIELDS:
            raise O.OpError(f"a sequence has no field {key!r} (it has title, purpose; its shots are changed with "
                            "sequence.bounds)")
        value = O.text(op.get("value"), key)
        entry = self._sequence(seq)
        old = entry[key]
        entry[key] = value
        return ({"op": "sequence.set", "id": seq, "field": key, "value": value},
                [Change("sequence.set", tuple(self.shots_in(seq)), key, detail={"sequence": seq, "old": old,
                                                                               "new": value})])

    def _contiguous(self) -> None:
        order = [s["sequence"] for s in self.plan["shots"]]
        runs = [q for i, q in enumerate(order) if i == 0 or order[i - 1] != q]
        twice = sorted({q for q in runs if runs.count(q) > 1})
        if twice:
            raise O.OpError(f"sequence {twice[0]} would be split in two places: a sequence is one run of shots")

    def _op_sequence_bounds(self, op: Row, addr: dict[int, str], arcs: Any, by: str) -> tuple[Row, list[Change]]:
        seq = self._sequence_id(op.get("id"))
        a, b = self._resolve(addr, op.get("first")), self._resolve(addr, op.get("last"))
        ia, ib = self.index_of(a), self.index_of(b)
        if ia > ib:
            raise O.OpError("the first shot of a sequence comes before its last")
        shots = self.plan["shots"]
        old = {s["_h"]: s["sequence"] for s in shots}
        for s in shots[ia:ib + 1]:
            s["sequence"] = seq
        # a shot that leaves the sequence joins the nearest sequence on its own side of the new span
        for i, s in enumerate(shots):
            if s["sequence"] == seq and not ia <= i <= ib:
                side = range(i - 1, -1, -1) if i < ia else range(i + 1, len(shots))
                near = next((shots[j]["sequence"] for j in side if shots[j]["sequence"] != seq), None)
                if near is None:
                    raise O.OpError(f"{self.code_of(s['_h'])} would be left with no sequence: give the shots "
                                    f"{'before' if i < ia else 'after'} the span a sequence first (sequence.add)")
                s["sequence"] = near
        self._contiguous()
        dropped = self._drop_empty_sequences()
        moved = tuple(h for h, q in old.items() if self.shot(h)["sequence"] != q)
        return ({"op": "sequence.bounds", "id": seq, "first": self.number_of(a), "last": self.number_of(b)},
                [Change("sequence.bounds", moved, "sequence", detail={"sequence": seq, "dropped": dropped})])

    def _op_sequence_add(self, op: Row, addr: dict[int, str], arcs: Any, by: str) -> tuple[Row, list[Change]]:
        ids = [q["id"] for q in self.plan["sequences"]]
        seq = str(op.get("id") or "").strip().upper() or next(
            c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c not in ids)
        if seq in ids:
            raise O.OpError(f"sequence {seq} already exists")
        a, b = self._resolve(addr, op.get("first")), self._resolve(addr, op.get("last"))
        ia, ib = self.index_of(a), self.index_of(b)
        if ia > ib:
            raise O.OpError("the first shot of a sequence comes before its last")
        before = self.plan["shots"][ia - 1]["sequence"] if ia > 0 else None
        entry = {"id": seq, "title": O.text(op.get("title", ""), "title"),
                 "purpose": O.text(op.get("purpose", ""), "purpose"), "shots": {"first": ia + 1, "last": ib + 1}}
        for s in self.plan["shots"][ia:ib + 1]:
            s["sequence"] = seq
        place = self.plan_sequence_index(before) + 1 if before else 0
        self.plan["sequences"].insert(place, entry)
        light = next((c["light"] for c in self.plan["treatment"]["colour_script"] if c.get("sequence") == before), "")
        self.plan["treatment"]["colour_script"].append({"sequence": seq, "palette": "", "light": light, "grade": ""})
        self.plan["treatment"]["colour_script"].sort(key=lambda c: self.plan_sequence_index(c["sequence"]))
        self._contiguous()
        self._drop_empty_sequences()
        return ({"op": "sequence.add", "id": seq, "first": ia + 1, "last": ib + 1, "title": entry["title"]},
                [Change("sequence.add", tuple(self.shots_in(seq)), "sequence", detail={"sequence": seq})])

    def _drop_empty_sequences(self) -> list[str]:
        """Sequences left with no shot go (with their colour entry); the rest are put in the order their shots play.
        → the ids that went."""
        order = list(dict.fromkeys(s["sequence"] for s in self.plan["shots"]))
        gone = [q["id"] for q in self.plan["sequences"] if q["id"] not in order]
        self.plan["sequences"] = sorted((q for q in self.plan["sequences"] if q["id"] in order),
                                        key=lambda q: order.index(q["id"]))
        self.plan["treatment"]["colour_script"] = sorted(
            (c for c in self.plan["treatment"]["colour_script"] if c.get("sequence") in order),
            key=lambda c: order.index(c["sequence"]))
        return gone

    def _op_sequence_remove(self, op: Row, addr: Any, arcs: Any, by: str) -> tuple[Row, list[Change]]:
        seq = self._sequence_id(op.get("id"))
        ids = [q["id"] for q in self.plan["sequences"]]
        if len(ids) <= 1:
            raise O.OpError("the scene needs at least one sequence")
        i = ids.index(seq)
        into = ids[i - 1] if i > 0 else ids[i + 1]
        mine = tuple(self.shots_in(seq))
        for h in mine:
            self.shot(h)["sequence"] = into
        self._drop_empty_sequences()
        return ({"op": "sequence.remove", "id": seq, "into": into},
                [Change("sequence.remove", mine, "sequence", detail={"sequence": seq, "into": into})])

    # ── shots ─────────────────────────────────────────────────────────────────────────────────

    def _op_set(self, op: Row, addr: dict[int, str], arcs: Any, by: str) -> tuple[Row, list[Change]]:
        handle = self._resolve(addr, op.get("shot"))
        key = str(op.get("field") or "")
        hint = {"take_s": "retime", "use_s": "use", "blocks": "split or merge", "lines": "nothing: lines follow their "
                "blocks", "sequence": "regroup", "ir": "ir.set", "sound": "sound.set", "n": "move"}
        if key in hint:
            raise O.OpError(f"{key} is changed with {hint[key]}, not set")
        if key not in O.SHOT_FIELDS:
            raise O.OpError(f"a shot has no settable field {key!r} (it has {', '.join(O.SHOT_FIELDS)})")
        value = O.text(op.get("value"), key)
        if key == "size":
            value = value.upper()
            if value not in O.SIZES:
                raise O.OpError(f"size must be one of {', '.join(O.SIZES)}")
        if key == "link":
            value = value.lower()
            if value not in O.LINKS:
                raise O.OpError(f"link must be one of {', '.join(O.LINKS)}")
            if self.index_of(handle) == 0 and value != "cut":
                raise O.OpError("the first shot has nothing to join")
        if key == "over" and value and value.casefold() not in {c.casefold() for c in self.scene.get("cast") or []}:
            raise O.OpError(f"{value} is not in this scene")
        shot = self.shot(handle)
        old = shot[key]
        shot[key] = value
        return ({"op": "set", "shot": self.number_of(handle), "field": key, "value": value},
                [Change("set", (handle,), key, detail={"old": old, "new": value})])

    def _op_retime(self, op: Row, addr: dict[int, str], arcs: Any, by: str) -> tuple[Row, list[Change]]:
        handle = self._resolve(addr, op.get("shot"))
        take = O.whole(op.get("take_s", op.get("seconds")), "take_s")
        if take not in O.TAKES:
            raise O.OpError("a take is 4, 6 or 8 seconds (what Veo makes)")
        shot = self.shot(handle)
        old = shot["take_s"]
        shot["take_s"] = take
        shot["use_s"] = min(shot["use_s"], take)
        if by in ("conductor", "person"):
            self.pinned.add(handle)
        return ({"op": "retime", "shot": self.number_of(handle), "take_s": take},
                [Change("retime", (handle,), "take_s", detail={"old": old, "new": take})])

    def _op_use(self, op: Row, addr: dict[int, str], arcs: Any, by: str) -> tuple[Row, list[Change]]:
        handle = self._resolve(addr, op.get("shot"))
        shot = self.shot(handle)
        use = O.whole(op.get("use_s", op.get("seconds")), "use_s")
        if not 2 <= use <= shot["take_s"]:
            raise O.OpError(f"the edit keeps 2 to {shot['take_s']} s of {self.code_of(handle)}'s {shot['take_s']} s "
                            "take (retime it for more)")
        old = shot["use_s"]
        shot["use_s"] = use
        return ({"op": "use", "shot": self.number_of(handle), "use_s": use},
                [Change("use", (handle,), "use_s", detail={"old": old, "new": use})])

    def _op_sound_set(self, op: Row, addr: dict[int, str], arcs: Any, by: str) -> tuple[Row, list[Change]]:
        handle = self._resolve(addr, op.get("shot"))
        key = str(op.get("field") or "")
        if key not in O.SOUND_FIELDS:
            raise O.OpError(f"a shot's sound has no field {key!r} (it has {', '.join(O.SOUND_FIELDS)})")
        raw = op.get("value")
        value: Any = raw if key == "silence" and isinstance(raw, bool) else (
            str(raw).strip().lower() in ("true", "yes", "1") if key == "silence" else O.text(raw, key))
        sound = self.shot(handle)["sound"]
        old = sound[key]
        sound[key] = value
        return ({"op": "sound.set", "shot": self.number_of(handle), "field": key, "value": value},
                [Change("sound.set", (handle,), f"sound.{key}", detail={"old": old, "new": value})])

    def _op_ir_set(self, op: Row, addr: dict[int, str], arcs: Any, by: str) -> tuple[Row, list[Change]]:
        handle = self._resolve(addr, op.get("shot"))
        path = str(op.get("path") or op.get("field") or "").strip().strip(".")
        top = path.split(".", 1)[0]
        if top not in O.IR_FIELDS:
            raise O.OpError(f"a shot's camera design has no part {top!r} (it has {', '.join(O.IR_FIELDS)})")
        if "value" not in op:
            raise O.OpError("ir.set needs a value")
        value = copy.deepcopy(op["value"])
        if isinstance(value, str):
            value = value.strip()[:O.MAX_TEXT]
        node = self.shot(handle)["ir"]
        keys = path.split(".")
        for k in keys[:-1]:
            nxt = node.get(k)
            if not isinstance(nxt, dict):
                nxt = {}
                node[k] = nxt
            node = nxt
        old = copy.deepcopy(node.get(keys[-1]))
        node[keys[-1]] = value
        return ({"op": "ir.set", "shot": self.number_of(handle), "path": path, "value": value},
                [Change("ir.set", (handle,), f"ir.{top}", detail={"path": path, "old": old})])

    def _op_regroup(self, op: Row, addr: dict[int, str], arcs: Any, by: str) -> tuple[Row, list[Change]]:
        handle = self._resolve(addr, op.get("shot"))
        seq = self._sequence_id(op.get("sequence"))
        shot = self.shot(handle)
        old = shot["sequence"]
        shot["sequence"] = seq
        self._contiguous()
        self._drop_empty_sequences()
        return ({"op": "regroup", "shot": self.number_of(handle), "sequence": seq},
                [Change("regroup", (handle,), "sequence", detail={"old": old, "new": seq})])

    # structure ──────────────────────────────────────────────────────────────────────────────────

    def _new_handle(self) -> str:
        self._new += 1
        return f"n{self._new}"

    def _bind(self, shot: Row) -> None:
        """A shot's lines, from the blocks it shows, in script order: Zora never writes a line (rule 6)."""
        lines = self.line_ids()
        shot["blocks"] = sorted(dict.fromkeys(int(b) for b in shot["blocks"]))
        shot["lines"] = [lines[b] for b in shot["blocks"] if b in lines]
        if not shot["lines"]:
            shot["over"] = ""

    def _demote_at(self, index: int) -> str:
        """The shot now at `index` has a new shot before it: a declared join to the old one becomes a cut."""
        shots = self.plan["shots"]
        if not 0 <= index < len(shots) or shots[index]["link"] == "cut":
            return ""
        shots[index]["link"] = "cut"
        return str(shots[index]["_h"])

    def _op_split(self, op: Row, addr: dict[int, str], arcs: Any, by: str) -> tuple[Row, list[Change]]:
        handle = self._resolve(addr, op.get("shot"))
        index = self.index_of(handle)
        shot = self.plan["shots"][index]
        blocks = sorted(shot["blocks"])
        if len(blocks) < 2:
            raise O.OpError(f"{self.code_of(handle)} shows {'one block' if blocks else 'no script block'}: there is "
                            "nothing to divide at a block boundary (insert a shot beside it instead)")
        at = O.whole(op["at_block"], "at_block") if op.get("at_block") is not None else blocks[len(blocks) // 2]
        if at not in blocks[1:]:
            raise O.OpError(f"{self.code_of(handle)} can be divided before " +
                            ", ".join(f"b{b}" for b in blocks[1:]) + f", not before b{at}")
        second = copy.deepcopy(shot)
        second["_h"] = self._new_handle()
        shot["blocks"] = [b for b in blocks if b < at]
        second["blocks"] = [b for b in blocks if b >= at]
        self._bind(shot)
        self._bind(second)
        original = shot["why"]
        shot["why"] = ""
        second.update({"why": "", "link": "cut"})
        second["ir"] = {k: v for k, v in second["ir"].items() if k in ("setting", "lighting")}
        shot["use_s"] = min(shot["use_s"], shot["take_s"])
        self.plan["shots"].insert(index + 1, second)
        return ({"op": "split", "shot": _start(addr, handle), "at_block": at},
                [Change("split", (handle, second["_h"]), "", detail={"why": original,
                                                                     "intent": str(op.get("intent") or "")[:600]})])

    def _op_merge(self, op: Row, addr: dict[int, str], arcs: Any, by: str) -> tuple[Row, list[Change]]:
        numbers = op.get("shots")
        if not isinstance(numbers, list) or len(numbers) != 2:
            raise O.OpError("merge takes exactly two shots that follow each other")
        a, b = (self._resolve(addr, n) for n in numbers)
        ia, ib = sorted((self.index_of(a), self.index_of(b)))
        if ib != ia + 1:
            raise O.OpError("only shots that follow each other can be merged")
        first, second = self.plan["shots"][ia], self.plan["shots"][ib]
        whys = [first["why"], second["why"]]
        first["blocks"] = [*first["blocks"], *second["blocks"]]
        self._bind(first)
        need = first["use_s"] + second["use_s"]
        first["take_s"] = next((t for t in O.TAKES if t >= need), max(O.TAKES))
        first["use_s"] = min(need, first["take_s"])
        first["over"] = first["over"] or second["over"]
        first["why"] = ""
        absorbed = second["_h"]
        for x in self.plan.get("added") or []:
            if x["shot"] == absorbed:
                x["shot"] = first["_h"]
        self.plan["shots"].pop(ib)
        return ({"op": "merge", "shots": [_start(addr, first["_h"]), _start(addr, absorbed)]},
                [Change("merge", (first["_h"],), "", detail={"whys": whys, "absorbed": absorbed,
                                                             "intent": str(op.get("intent") or "")[:600]})])

    def _op_insert(self, op: Row, addr: dict[int, str], arcs: Any, by: str) -> tuple[Row, list[Change]]:
        after = O.shot_number(op.get("after", 0))
        anchor = None if after == 0 else self._resolve(addr, after, "after")
        kind = str(op.get("kind") or "").strip().lower()
        if kind not in O.ADDED_KINDS:
            raise O.OpError(f"an added shot is one of {', '.join(O.ADDED_KINDS)}, not {kind!r}")
        who = op.get("who") or []
        who = [str(w).strip() for w in (who if isinstance(who, list) else [who]) if str(w).strip()]
        cast = {c.casefold(): c for c in self.scene.get("cast") or []}
        stranger = next((w for w in who if w.casefold() not in cast), "")
        if stranger:
            raise O.OpError(f"{stranger} is not in this scene")
        chain_key = anchor or "^"
        prev = self._chain.get(chain_key, anchor)
        index = 0 if prev is None else self.index_of(prev) + 1
        shots = self.plan["shots"]
        near = shots[index - 1] if index > 0 else shots[0] if shots else None
        size = str(op.get("size") or SIZE_FOR.get(kind, "MS")).upper()
        if size not in O.SIZES:
            raise O.OpError(f"size must be one of {', '.join(O.SIZES)}")
        handle = self._new_handle()
        ir = {k: copy.deepcopy(v) for k, v in (near or {}).get("ir", {}).items() if k in ("setting", "lighting")}
        new = {"n": 0, "sequence": (near or {}).get("sequence") or self.plan["sequences"][0]["id"], "blocks": [],
               "lines": [], "over": "", "size": size, "angle": "", "lens": "", "take_s": 4, "use_s": 2,
               "link": "cut", "why": "", "ir": ir,
               "sound": {"ambience": str(((near or {}).get("sound") or {}).get("ambience") or ""), "effects": "",
                         "music": "", "silence": True},
               "_h": handle}
        shots.insert(index, new)
        self._chain[chain_key] = handle
        what = O.text(op.get("what") or op.get("intent") or "", "what")
        self.plan.setdefault("added", []).append(
            {"shot": handle, "kind": kind, "what": what, "who": [cast[w.casefold()] for w in who],
             "object": O.text(op.get("object") or "", "object")})
        demoted = self._demote_at(index + 1)
        return ({"op": "insert", "after": after, "kind": kind, "what": what, "who": who},
                [Change("insert", (handle,), "", detail={"intent": what, "kind": kind, "demoted": demoted})])

    def _scripted(self, handle: str, verb: str) -> None:
        shot = self.shot(handle)
        if shot["blocks"]:
            blocks = sorted(shot["blocks"])
            shown = f"b{blocks[0]}" + (f"–b{blocks[-1]}" if len(blocks) > 1 else "")
            lines = f" ({', '.join(shot['lines'])})" if shot["lines"] else ""
            raise O.OpError(f"{self.code_of(handle)} shows {shown}{lines} of the script; {verb} it would "
                            + ("drop the script: merge it into the shot before or after instead" if verb == "removing"
                               else "put the script out of order: shots play in script order"))

    def _op_remove(self, op: Row, addr: dict[int, str], arcs: Any, by: str) -> tuple[Row, list[Change]]:
        handle = self._resolve(addr, op.get("shot"))
        self._scripted(handle, "removing")
        if len(self.plan["shots"]) <= 1:
            raise O.OpError("a scene needs at least one shot")
        index = self.index_of(handle)
        gone = self.plan["shots"].pop(index)
        added = [a for a in self.plan.get("added") or [] if a["shot"] == handle]
        self.plan["added"] = [a for a in self.plan.get("added") or [] if a["shot"] != handle]
        demoted = self._demote_at(index)
        self._drop_empty_sequences()
        near = tuple(self.plan["shots"][i]["_h"] for i in (index - 1, index) if 0 <= i < len(self.plan["shots"]))
        return ({"op": "remove", "shot": _start(addr, handle), "was": gone["why"][:120]},
                [Change("remove", near, "", detail={"removed": handle, "added": added, "demoted": demoted,
                                                    "why": gone["why"]})])

    def _op_move(self, op: Row, addr: dict[int, str], arcs: Any, by: str) -> tuple[Row, list[Change]]:
        handle = self._resolve(addr, op.get("shot"))
        self._scripted(handle, "moving")
        after = O.shot_number(op.get("after", 0))
        anchor = None if after == 0 else self._resolve(addr, after, "after")
        if anchor == handle:
            raise O.OpError("a shot cannot move after itself")
        old = self.index_of(handle)
        moving = self.plan["shots"].pop(old)
        demoted = [self._demote_at(old)]
        index = 0 if anchor is None else self.index_of(anchor) + 1
        self.plan["shots"].insert(index, moving)
        moving["link"] = "cut"
        near = self.plan["shots"][index - 1] if index > 0 else self.plan["shots"][min(1, len(self.plan["shots"]) - 1)]
        moving["sequence"] = near["sequence"]
        demoted.append(self._demote_at(index + 1))
        self._contiguous()
        self._drop_empty_sequences()
        return ({"op": "move", "shot": _start(addr, handle), "after": after},
                [Change("move", (handle,), "", detail={"demoted": [d for d in demoted if d]})])

    # ── staging and the end state ─────────────────────────────────────────────────────────────

    def _who(self, value: Any) -> str:
        who = str(value or "").strip()
        cast = {c.casefold(): c for c in self.scene.get("cast") or []}
        if who.casefold() not in cast:
            raise O.OpError(f"{who or 'that person'} is not in this scene (present: {', '.join(cast.values())})")
        return cast[who.casefold()]

    def _mark(self, op: Row) -> tuple[int, str, Row | None]:
        block = O.whole(op.get("block"), "block")
        if block not in self.block_indices():
            raise O.OpError(f"there is no block b{block}")
        who = self._who(op.get("who"))
        mark = next((m for m in self.plan["staging"]["marks"] if m["block"] == block and m["who"] == who), None)
        return block, who, mark

    def _mark_value(self, key: str, value: Any) -> str:
        v = O.text(value, key)
        if key == "facing" and v not in O.FACINGS:
            raise O.OpError(f"facing is one of {', '.join(f for f in O.FACINGS if f)}")
        if key == "frame_side" and v not in O.FRAME_SIDES:
            raise O.OpError("frame_side is one of left, right, centre")
        if key == "zone" and v.casefold() not in {z.casefold() for z in self.plan["staging"]["zones"]} | {"off"}:
            raise O.OpError(f"there is no zone {v!r} (zones: {', '.join(self.plan['staging']['zones'])}; zone.add "
                            "makes one)")
        return v

    def _op_mark_set(self, op: Row, addr: Any, arcs: Any, by: str) -> tuple[Row, list[Change]]:
        block, who, mark = self._mark(op)
        if mark is None:
            raise O.OpError(f"{who} has no mark at b{block} (mark.add makes one)")
        key = str(op.get("field") or "")
        if key not in O.MARK_FIELDS:
            raise O.OpError(f"a mark has no field {key!r} (it has {', '.join(O.MARK_FIELDS)})")
        old = mark[key]
        mark[key] = self._mark_value(key, op.get("value"))
        return ({"op": "mark.set", "block": block, "who": who, "field": key, "value": mark[key]},
                [Change("mark.set", (), key, detail={"block": block, "who": who, "old": old})])

    def _op_mark_add(self, op: Row, addr: Any, arcs: Any, by: str) -> tuple[Row, list[Change]]:
        block, who, mark = self._mark(op)
        if mark is not None:
            raise O.OpError(f"{who} already has a mark at b{block} (mark.set changes it)")
        new = {"block": block, "who": who, **{k: self._mark_value(k, op.get(k, "")) if k != "zone" or op.get(k)
                                              else self._mark_value(k, "off") for k in O.MARK_FIELDS}}
        self.plan["staging"]["marks"].append(new)
        self.plan["staging"]["marks"].sort(key=lambda m: (m["block"], m["who"]))
        return ({"op": "mark.add", **new}, [Change("mark.add", (), "marks", detail={"block": block, "who": who})])

    def _op_mark_remove(self, op: Row, addr: Any, arcs: Any, by: str) -> tuple[Row, list[Change]]:
        block, who, mark = self._mark(op)
        if mark is None:
            raise O.OpError(f"{who} has no mark at b{block}")
        self.plan["staging"]["marks"].remove(mark)
        return ({"op": "mark.remove", "block": block, "who": who},
                [Change("mark.remove", (), "marks", detail={"block": block, "who": who})])

    def _op_zone_add(self, op: Row, addr: Any, arcs: Any, by: str) -> tuple[Row, list[Change]]:
        zone = O.text(op.get("zone") or op.get("value"), "zone")
        if not zone or zone.casefold() in {z.casefold() for z in self.plan["staging"]["zones"]}:
            raise O.OpError(f"the zone {zone!r} is empty or already there")
        self.plan["staging"]["zones"].append(zone)
        return ({"op": "zone.add", "zone": zone}, [Change("zone.add", (), "zones", detail={"zone": zone})])

    def _op_end_set(self, op: Row, addr: Any, arcs: Any, by: str) -> tuple[Row, list[Change]]:
        key = str(op.get("field") or "")
        end = self.plan["end_state"]
        if not op.get("who"):
            if key not in O.END_FIELDS:
                raise O.OpError(f"the end state has no field {key!r} (time, light; or a person's "
                                f"{', '.join(O.END_PERSON_FIELDS)})")
            old = end[key]
            end[key] = O.text(op.get("value"), key)
            return ({"op": "end.set", "field": key, "value": end[key]},
                    [Change("end.set", (), key, detail={"old": old})])
        who = self._who(op.get("who"))
        if key not in O.END_PERSON_FIELDS:
            raise O.OpError(f"a person's end state has no field {key!r} (it has {', '.join(O.END_PERSON_FIELDS)})")
        person = next((p for p in end["people"] if p["who"] == who), None)
        if person is None:
            person = {"who": who, "where": "", "facing": "", "holding": "", "look": ""}
            end["people"].append(person)
        old = person[key]
        person[key] = O.text(op.get("value"), key)
        return ({"op": "end.set", "who": who, "field": key, "value": person[key]},
                [Change("end.set", (), key, detail={"who": who, "old": old})])

    # ── locks (a person's click) ──────────────────────────────────────────────────────────────

    def _op_lock(self, op: Row, addr: Any, arcs: Any, by: str) -> tuple[Row, list[Change]]:
        path = str(op.get("path") or "").strip()
        if not path:
            raise O.OpError("lock needs a path")
        self.locked = list(dict.fromkeys([*self.locked, self._to_handles(path)]))
        return {"op": "lock", "path": path}, [Change("lock", (), path)]

    def _op_unlock(self, op: Row, addr: Any, arcs: Any, by: str) -> tuple[Row, list[Change]]:
        path = self._to_handles(str(op.get("path") or "").strip())
        if path not in self.locked:
            raise O.OpError(f"{op.get('path')!r} is not locked")
        self.locked.remove(path)
        return {"op": "unlock", "path": op.get("path")}, [Change("unlock", (), str(op.get("path")))]


def settle(kernel: ZoraKernel, path: str) -> None:
    """A choice the person handed over ("you decide the lens"): it may never be asked about again (Nova §10ad)."""
    kernel.settled = list(dict.fromkeys([*kernel.settled, kernel._to_handles(path)]))


def _who(by: str) -> str:
    return {"author": "the author", "repair": "the author's repair", "conductor": "the conductor",
            "translator": "the translator", "person": "a person", "code": "code"}.get(by, by)


def _range(n: int) -> str:
    return f"{O.code(1)}–{O.code(n)}" if n > 1 else O.code(1) if n == 1 else "no shots"


def _start(addr: dict[int, str], handle: str) -> int | None:
    """The number a handle had at the start of the batch (for reporting a shot that moved or went)."""
    return next((n for n, h in addr.items() if h == handle), None)


def _plain(entry: Row) -> Row:
    return {k: v for k, v in entry.items() if k != "_h"}
