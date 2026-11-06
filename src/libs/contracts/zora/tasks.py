"""A piece of the author's work in one Zora turn (plan/2026-11-06e §4.3, §4.5; Nova `deps.Task`).

Raised by the conductor (what the person asked for), by the dependency graph (what an edit made stale, proven by code),
by the delivery check (asked for, not yet done) or by the gate (a fault this turn introduced). Pure standard library.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Task:
    """One piece of the author's work this turn. `writes`: the effects it MUST deliver (checked against the diff);
    `may`: further effects it is allowed to write; `scope`: kernel handles (() = the whole scene)."""

    writes: tuple[str, ...]
    scope: tuple[str, ...] = ()
    instruction: str = ""
    reason: str = ""
    may: tuple[str, ...] = ()
    origin: str = "deps"  # conductor | deps | delivery | repair
    user_asked: bool = False
    sequence: str = ""

    @property
    def allowed(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.writes + self.may))

    def data(self) -> dict[str, Any]:
        return {"writes": list(self.writes), "may": list(self.may), "scope": list(self.scope),
                "instruction": self.instruction, "reason": self.reason, "origin": self.origin,
                "user_asked": self.user_asked, "sequence": self.sequence}


def merge_tasks(tasks: list[Task]) -> list[Task]:
    """Tasks with the same scope become one (their effects and instructions joined). An EMPTY scope is the whole scene
    and absorbs the rest when effects overlap (Nova: unioning a whole-scene scope with a partial one narrowed it)."""
    out: list[Task] = []
    for task in tasks:
        same = next((t for t in out if t.scope == task.scope), None)
        if same is None:
            out.append(Task(**{**task.__dict__}))
            continue
        same.writes = tuple(dict.fromkeys(same.writes + task.writes))
        same.may = tuple(dict.fromkeys(same.may + task.may))
        same.user_asked = same.user_asked or task.user_asked
        for key in ("instruction", "reason"):
            mine, theirs = getattr(same, key), getattr(task, key)
            if theirs and theirs not in mine:
                setattr(same, key, "; ".join(p for p in (mine, theirs) if p))
    return out
