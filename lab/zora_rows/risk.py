"""The risk rule (plan/2026-11-12d §3.4, D5): from the operations that landed, code decides whether the turn saves now or
waits for the person's Accept. Never a model.

    reasons(applied, before, after, left) -> [str]   empty: safe, save now; else: show a card, save nothing
    consequences(before, after, notes, found) -> [str] the plain lines the card shows
"""

from __future__ import annotations

from typing import Any

from checks import Finding
from coverage import Coverage
from kernel import lock_key

Row = dict[str, Any]
MOST = 0.5  # an edit that changes more than this share of the clips asks first


def _changed(before: Coverage, after: Coverage) -> set[str]:
    old = {c.h: c for c in before.clips}
    out = set()
    for c in after.clips:
        o = old.get(c.h)
        if o is None or (o.size, o.take_s, o.link, o.why, o.sees, o.ir, o.sound, o.first, o.last, o.role,
                         o.priority) != (c.size, c.take_s, c.link, c.why, c.sees, c.ir, c.sound, c.first, c.last,
                                         c.role, c.priority):
            out.add(c.h)
    out |= {h for h in old if after.clip(h) is None}
    return out


def reasons(applied: list[Row], before: Coverage, after: Coverage, left: list[Finding]) -> list[str]:
    why: list[str] = []
    for a in applied:
        op, by = a["op"], a["by"]
        name = op.get("op")
        if name == "remove":
            ref = before.at(op.get("shot"))
            if ref is not None:
                lines = before.performs(ref.h)
                if ref.priority == "must":
                    why.append(f"removes {before.code(ref.h)}, a must clip")
                if lines:
                    why.append(f"removes the clip that performs {', '.join(ln.lid for ln in lines)}")
        elif name in ("split", "merge"):
            why.append(f"a {name}")
        elif name == "role":
            why.append("changes a clip's role")
        elif name == "line":
            why.append(f"moves {op.get('line')} to another clip")
        key = lock_key(op)
        ref = before.at(op.get("shot")) if op.get("shot") is not None else None
        if by == "conductor" and key and ref is not None and key in ref.locks:
            why.append(f"changes {before.code(ref.h)}'s {key}, which a person set")
    changed = {h for h in _changed(before, after) if before.clip(h) is not None}  # Sable prod2: "7 of 6 clips"
    if before.clips and len(changed) > MOST * len(before.clips):
        why.append(f"changes {len(changed)} of {len(before.clips)} clips")
    if left:
        why.append(f"leaves {len(left)} new problem{'s' if len(left) > 1 else ''} the repair could not fix")
    return list(dict.fromkeys(why))


def consequences(before: Coverage, after: Coverage, done: list[str], notes: list[str], found: list[Finding]) -> list[str]:
    out = list(done) + list(notes)
    if before.total_s() != after.total_s():
        out.append(f"Takes in the scene: {before.total_s()} s → {after.total_s()} s")
    out.append("Checks after the change: " + ("no new problem" if not found else
                                              "; ".join(f.sentence for f in found[:3])))
    return out
