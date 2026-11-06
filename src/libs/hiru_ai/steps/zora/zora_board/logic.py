"""Zora's board (plan/2026-11-06e §4.6 step 1; Nova Studio's `board.py`, kept as allow-lists for ONE author).

With one author there are no seat collisions to settle, so what remains of Nova's board is the part that keeps the
author honest about its brief:

* an op outside every task's allow-list (its effect, on a shot in the task's scope) is refused;
* an op on a path the person locked is refused, with a reason the person recognises ("you set S04's lens");
* an op that re-sends the value already there is dropped as a no-op (Nova `is_noop`), counted, never reported as work;
* an op that would put words in a line is refused (lines are the script's).

Every refusal is kept for the ledger (Nova W5: the team's refused work is a fact the person is owed, not telemetry).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

from contracts.zora import ops as O

Row = dict[str, Any]
UNKNOWN = object()


def op_effects(op: Row) -> tuple[str, ...]:
    """The effects (`contracts.zora.effects.WRITES` keys) an op produces."""
    name = str(op.get("op") or "")
    f = str(op.get("field") or "")
    if name == "set":
        return (f"shot.{f}",)
    if name == "retime":
        return ("shot.take_s",)
    if name == "use":
        return ("shot.use_s",)
    if name == "sound.set":
        return (f"shot.sound.{f}",)
    if name == "ir.set":
        return (f"shot.ir.{str(op.get('path') or op.get('field') or '').split('.')[0]}",)
    if name in ("split", "merge", "move"):
        return ("shot.order",)
    if name in ("insert", "remove"):
        return ("shot.order", "shot.added")
    if name in ("regroup", "sequence.bounds", "sequence.add", "sequence.remove"):
        return ("sequence.bounds",)
    if name == "sequence.set":
        return (f"sequence.{f}",)
    if name == "treatment.set":
        return (f"treatment.{f}",)
    if name.startswith("arc."):
        return ("treatment.arc",)
    if name == "colour.set":
        return ("treatment.colour",)
    if name.startswith("mark."):
        return ("staging.marks",)
    if name == "zone.add":
        return ("staging.zones",)
    if name == "end.set":
        return ("end_state",)
    return (name,)


def op_shots(op: Row) -> list[int]:
    """The shot numbers an op names (as the plan stands when the author reads it)."""
    name = str(op.get("op") or "")
    try:
        if name == "merge":
            return [O.shot_number(n) for n in op.get("shots") or []]
        if name == "insert":
            after = O.shot_number(op.get("after") or 0)
            return [after] if after else []
        if name == "sequence.bounds" or name == "sequence.add":
            return [O.shot_number(op.get("first")), O.shot_number(op.get("last"))]
        if op.get("shot") is not None:
            return [O.shot_number(op["shot"])]
    except O.OpError:
        return []
    return []


def current(plan: Row, op: Row) -> Any:
    """What the plan holds where a whole-value op writes, or UNKNOWN."""
    name = str(op.get("op") or "")
    f = str(op.get("field") or "")
    try:
        if name == "treatment.set":
            return plan["treatment"][f]
        if name == "colour.set":
            return next(c[f] for c in plan["treatment"]["colour_script"] if c["sequence"] == op.get("sequence"))
        if name == "sequence.set":
            return next(q[f] for q in plan["sequences"] if q["id"] == str(op.get("id") or "").upper())
        shot = plan["shots"][O.shot_number(op.get("shot")) - 1] if op.get("shot") is not None else None
        if shot is not None and name == "set":
            return shot[f]
        if shot is not None and name == "retime":
            return shot["take_s"]
        if shot is not None and name == "use":
            return shot["use_s"]
        if shot is not None and name == "sound.set":
            return shot["sound"][f]
        if shot is not None and name == "ir.set":
            node: Any = shot["ir"]
            for k in str(op.get("path") or "").split("."):
                node = node[k]
            return node
    except (KeyError, IndexError, StopIteration, TypeError, O.OpError):
        return UNKNOWN
    return UNKNOWN


def is_noop(op: Row, live: Any) -> bool:
    """Does this op write the value already there? Conservative: anything it cannot compare is a real claim."""
    if live is UNKNOWN:
        return False
    name = str(op.get("op") or "")
    value = op.get("take_s", op.get("seconds")) if name == "retime" else \
        op.get("use_s", op.get("seconds")) if name == "use" else op.get("value", UNKNOWN)
    if value is UNKNOWN:
        return False
    if isinstance(value, str) and isinstance(live, str):
        return value.strip() == live.strip()
    return bool(value == live)


@dataclass
class Settled:
    kept: list[Row] = dc_field(default_factory=list)
    refused: list[str] = dc_field(default_factory=list)  # sentences for the ledger
    noops: int = 0


def describe(op: Row) -> str:
    """An op as the person reads it in a refusal."""
    name = str(op.get("op") or "")
    shots = op_shots(op)
    where = O.code(shots[0]) if shots else ""
    what = {"set": f"{op.get('field')}", "retime": "take", "use": "kept seconds", "sound.set": f"{op.get('field')}",
            "ir.set": f"{str(op.get('path') or '').split('.')[0]}", "treatment.set": f"{op.get('field')}",
            "colour.set": f"sequence {op.get('sequence')}'s {op.get('field')}",
            "sequence.set": f"sequence {op.get('id')}'s {op.get('field')}"}.get(name, name)
    return f"{what} change on {where}" if where and name not in ("split", "merge", "insert", "remove", "move") \
        else f"{name} of {where}" if where else f"{what} change"


def settle(ops: list[Any], tasks: list[Any], plan: Row, *, handles: list[str], locked: list[str],
           seat: str = "the director") -> Settled:
    """Filter the author's ops. `plan` is the plan the author read (numbers as it saw them), `handles` the kernel's
    handles in that order, `locked` the kernel's locked paths (handle form), `tasks` the turn's `Task`s."""
    out = Settled()
    for raw in ops:
        op = O.infer_op(raw)
        if not isinstance(op, dict) or not op.get("op"):
            out.refused.append(f"{seat}: an answer that was not an operation was ignored")
            continue
        name = str(op.get("op") or "").lower()
        op = {**op, "op": name}
        if any(k in op for k in ("lines", "line", "text")) or str(op.get("field") or "") in ("lines", "blocks"):
            out.refused.append(f"{seat}'s {describe(op)} was refused: the script's lines are never written by the "
                               "team")
            continue
        if is_noop(op, current(plan, op)):  # noise, not work: dropped before it can be refused
            out.noops += 1
            continue
        effects = op_effects(op)
        numbers = op_shots(op)
        own = {handles[n - 1] for n in numbers if 1 <= n <= len(handles)}
        if not any(set(effects) & set(t.allowed) and (not t.scope or own <= set(t.scope) or not own)
                   for t in tasks):
            out.refused.append(f"{seat}'s {describe(op)} was refused: it was outside what this turn asked for")
            continue
        paths = []
        for path in O.path_of(op).split("+"):
            head, dot, rest = path.partition(".")
            n = int(head[1:]) if head[:1] == "S" and head[1:].isdigit() else 0
            paths.append(f"#{handles[n - 1]}{dot}{rest}" if 1 <= n <= len(handles) else path)
        hit = next((p for p in paths for lk in locked if p == lk or p.startswith(lk + ".")), "")
        if hit:
            shown = f"{O.code(handles.index(hit[1:].split('.')[0]) + 1)}" if hit.startswith("#") else ""
            out.refused.append(f"{seat}'s {describe(op)} was refused: you set "
                               + (f"{shown}'s {hit.split('.', 1)[1]}" if shown and "." in hit else shown or hit)
                               + " yourself")
            continue
        out.kept.append(copy.deepcopy(op))
    return out
