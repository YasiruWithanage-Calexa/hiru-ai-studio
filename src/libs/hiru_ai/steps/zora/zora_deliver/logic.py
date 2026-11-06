"""Zora's delivery check (plan/2026-11-06e §4.6 step 5; Nova W7 "effects declared vs delivered").

Every task declares the effects it exists to deliver. After the author (and the gate) code reads the DIFF:

    undelivered(tasks, before, after)   declared effects that did not change, each on the shots it was asked for
                                        (paired by handle: an insert earlier in the turn must not shift the comparison)
    retask(missing, tasks, locked)      ONE more task for what is missing; an effect the person locked, or one only the
                                        person can make (the end state), is never re-tasked, only reported
    report(missing, tasks, locked)      the lines "asked for this turn but not changed" the reply must say

A false "not done" is the same lie as a false "done" in the other direction, so an effect the check cannot pair (every
shot in its scope was removed) is read on the whole plan.
"""
from __future__ import annotations

from typing import Any

from contracts.zora import effects as E
from contracts.zora.tasks import Task

Row = dict[str, Any]
# effect → the field path under a shot that a lock on it covers (`S03.lens`), when it has one
_SHOT_PATH = {**{f"shot.{f}": f for f in ("size", "angle", "lens", "link", "why", "over")},
              "shot.take_s": "take_s", "shot.use_s": "use_s",
              **{f"shot.sound.{f}": f"sound.{f}" for f in ("ambience", "effects", "music", "silence")},
              **{f"shot.ir.{f}": f"ir.{f}" for f in ("setting", "cinematography", "lighting", "subjects", "beats",
                                                    "audio", "first_frame")}}


def undelivered(tasks: list[Task], before: Row, after: Row) -> list[str]:
    """Declared effects (`Task.writes`) the diff does not show, in the order they were declared."""
    out: list[str] = []
    live = {str(s.get("_h")) for s in after.get("shots") or []}
    for task in tasks:
        scope = {h for h in task.scope if h in live} or None if task.scope else None
        changed = E.changed_effects(before, after, scope)
        for effect in task.writes:
            if effect not in changed and effect not in out:
                out.append(effect)
    return out


def locked_effect(effect: str, task: Task | None, locked: list[str], handles: list[str]) -> bool:
    """Is every place this effect could change locked by the person?"""
    path = _SHOT_PATH.get(effect)
    if path is not None:
        scope = [h for h in (task.scope if task and task.scope else handles) if h in handles]
        return bool(scope) and all(any(f"#{h}.{path}" == lk or f"#{h}.{path}".startswith(lk + ".") or lk == f"#{h}"
                                       for lk in locked) for h in scope)
    if effect.startswith("treatment."):
        return effect in locked or "treatment" in locked
    return False


def _task_of(effect: str, tasks: list[Task]) -> Task | None:
    return next((t for t in tasks if effect in t.writes), None)


def retask(missing: list[str], tasks: list[Task], *, locked: list[str], handles: list[str]) -> list[Task]:
    """One task per scope for what is still undone, told it was asked for and has not changed yet."""
    out: list[Task] = []
    for effect in missing:
        task = _task_of(effect, tasks)
        spec = E.WRITES.get(effect)
        if task is None or spec is None or spec.owner != "author" or locked_effect(effect, task, locked, handles):
            continue
        same = next((t for t in out if t.scope == task.scope), None)
        if same is None:
            out.append(Task((effect,), task.scope, instruction=task.instruction, reason="asked for and not yet done",
                            may=task.may, origin="delivery", user_asked=task.user_asked, sequence=task.sequence))
        else:
            same.writes = (*same.writes, effect)
    for t in out:
        t.instruction = "; ".join(p for p in (t.instruction, "THIS WAS ASKED FOR AND HAS NOT CHANGED YET: "
                                              + ", ".join(E.label(e) for e in t.writes)
                                              + ". An empty answer leaves the request undone") if p)
    return out


def report(missing: list[str], tasks: list[Task], *, locked: list[str], handles: list[str]) -> list[str]:
    """The ledger's "asked for, not done" lines."""
    out = []
    for effect in missing:
        task = _task_of(effect, tasks)
        spec = E.WRITES.get(effect)
        note = (" (you set it yourself, so the team could not change it)"
                if locked_effect(effect, task, locked, handles) else
                " (only your own words can change this: say how it should end)" if spec and spec.owner == "conductor"
                else "")
        out.append(E.label(effect) + note)
    return out
