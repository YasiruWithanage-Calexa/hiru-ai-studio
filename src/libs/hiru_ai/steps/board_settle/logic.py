"""Who wins when two crafts write the same path (ownership), and what the loser still gets to say.

The pure half of the board: the specialists that propose operations are agents (Phase 4); settling their
proposals is code. Forked from PromptMotion `nova_chat/studio/board.py` (1d748dc)."""
from __future__ import annotations

# Ported from services/director_chat/director_chat/engine/agents.py (plan/2026-11-03 Phase 2).
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Output:
    agent: str
    ops: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""


def owner_by_table(op: dict[str, Any], owners: dict[str, str]) -> str:
    """Who wins a collision on this operation, from a panel's table (member `wins:` entries → member name). The most
    specific entry wins: "beat.set.camera" before "beat.set" before "*"; no entry at all falls to the legacy rule."""
    name, fld = op.get("op", ""), op.get("field")
    for key in (f"{name}.{fld}" if fld else "", name, "*"):
        if key and key in owners:
            return owners[key]
    return owner_of(op)


def owner_of(op: dict[str, Any]) -> str:
    name = op.get("op", "")
    if name == "set":
        return "sound" if op.get("field") == "sound_mode" else "cinematography"
    if name == "beat.set":
        return "cinematography" if op.get("field") == "camera" else "continuity"
    if name in ("split", "merge", "regroup"):
        return "timing"
    if name == "set_join":
        return "cinematography"
    return "cinematography"


def op_key(op: dict[str, Any]) -> str:
    name = op.get("op", "")
    if name == "set":
        return f"shot{op.get('shot')}.{op.get('field')}"
    if name == "beat.set":
        return f"shot{op.get('shot')}.beat{op.get('beat')}.{op.get('field')}"
    if name == "set_join":
        return f"shot{op.get('shot')}.camera_link"
    if name in ("split", "merge", "regroup", "remove"):
        return f"shot{op.get('shot')}.structure"
    return f"{name}:{op.get('after_shot', op.get('shot'))}"


MAX_OPS_PER_TASK = 6


def in_scope(op: dict[str, Any], shots: list[int]) -> bool:
    """A specialist may change only the shots its task names (an empty list is the whole scene).
    An insert counts as touching the shot it follows."""
    if not shots:
        return True
    target = op.get("after_shot") if op.get("op") == "insert" else op.get("shot")
    try:
        return int(str(target)) in shots
    except (TypeError, ValueError):
        return False


@dataclass
class Settled:
    ops: list[tuple[str, dict[str, Any]]] = field(default_factory=list)  # (agent, op) in apply order
    disagreements: list[dict[str, Any]] = field(default_factory=list)  # {title, positions}


def settle(outputs: list[Output], owners: dict[str, str] | None = None) -> Settled:
    """Owner wins a collision; the rival is heard, not applied. `owners` is the panel's table (see `owner_by_table`);
    without one the built-in rule decides, as before."""
    claims: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for out in outputs:
        for op in out.ops:
            claims.setdefault(op_key(op), []).append((out.agent, op))
    settled = Settled()
    notes = {o.agent: o.note for o in outputs}
    for claimants in claims.values():
        if len(claimants) == 1:
            settled.ops.append(claimants[0])
            continue
        owner = owner_by_table(claimants[0][1], owners) if owners else owner_of(claimants[0][1])
        winner = next((c for c in claimants if c[0] == owner), None)
        if winner is not None:
            settled.ops.append(winner)
        losers = [c for c in claimants if c is not winner]
        # Each side keeps its own operation (the same object the board applies), so the turn can
        # mark which one landed and a director can still choose the other later.
        settled.disagreements.append({
            "title": f"Two views on {op_label(claimants[0][1])}",
            "positions": [{"who": c[0].capitalize(), "text": notes.get(c[0]) or "", "ops": [c[1]]}
                          for c in ([winner] if winner else []) + losers]})
    return settled


def op_label(op: dict[str, Any]) -> str:
    """What two specialists both wrote, as a person reads it: "S02 beat 3 camera"."""
    try:
        n = f"S{int(op['after_shot'] if op.get('op') == 'insert' else op['shot']):02d}"
    except (KeyError, TypeError, ValueError):
        n = "the scene"
    name = op.get("op", "")
    if name == "set":
        return f"{n} {str(op.get('field', '')).replace('_', ' ')}"
    if name == "beat.set":
        try:
            beat = f"beat {int(op['beat']) + 1}"
        except (KeyError, TypeError, ValueError):
            beat = "a beat"
        return f"{n} {beat} {str(op.get('field', '')).replace('_', ' ')}"
    if name == "set_join":
        return f"how {n} joins"
    if name == "insert":
        return f"a new shot after {n}"
    return f"where {n} cuts"
