"""Treatment mode (plan/2026-11-06e §4.9; Nova brief mode, `brief_gaps` / `is_hard`, §10ad).

When a scene has no shots yet, or the person wants to work on the treatment, Zora edits only the treatment and the
sequences. What is still missing is a GAP:

    hard   the arc does not cover every script block (the planner cannot plan shots from it)
    soft   the approach, the colour script, the geography or the key image is empty

"You decide" SETTLES the soft gaps: the author fills them, and the reply may never ask about a settled one again. A
SUGGESTION is a button above the composer; pressing it sends its message, which code recognises, so no router is asked.

Pure standard library + pydantic.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

SOFT: dict[str, str] = {"treatment.approach": "the approach", "treatment.colour": "the colour script",
                        "treatment.geography": "the geography", "treatment.key_image": "the key image"}
TREATMENT_EFFECTS: frozenset[str] = frozenset({"treatment.logline", "treatment.approach", "treatment.geography",
                                               "treatment.key_image", "treatment.arc", "treatment.colour",
                                               "sequence.title", "sequence.purpose", "sequence.bounds"})
DRAFT_ARC = "Draft the arc"
YOU_DECIDE = "You decide the rest"
PLAN_SHOTS = "Plan shots from this treatment"


class Gap(BaseModel):
    effect: str
    label: str
    hard: bool = False


def _blocks(scene: dict[str, Any]) -> set[int]:
    return {int(b["index"]) for b in scene.get("blocks") or [] if b.get("index") is not None}


def gaps(plan: dict[str, Any], scene: dict[str, Any], *, settled: list[str] | None = None) -> list[Gap]:
    """What the treatment still lacks, hard first. A soft gap the person handed over (`settled`) is not one."""
    t = plan.get("treatment") or {}
    covered: set[int] = set()
    for a in t.get("arc") or []:
        span = a.get("blocks") or {}
        covered.update(range(int(span.get("first", 0)), int(span.get("last", -1)) + 1))
    out = []
    missing = sorted(_blocks(scene) - covered)
    if missing:
        out.append(Gap(effect="treatment.arc", label=f"the arc does not cover block{'s' if len(missing) > 1 else ''} "
                       + ", ".join(f"b{b}" for b in missing[:6]), hard=True))
    done = set(settled or [])
    for effect, label in SOFT.items():
        if effect in done:
            continue
        value = t.get("colour_script") if effect == "treatment.colour" else t.get(effect.split(".", 1)[1])
        if not value or (isinstance(value, str) and not value.strip()):
            out.append(Gap(effect=effect, label=label))
    return out


def treatment_mode(plan: dict[str, Any]) -> bool:
    """A plan with no shots yet: only the treatment and the sequences can be written."""
    return not plan.get("shots")


def suggestions(plan: dict[str, Any], scene: dict[str, Any], *, settled: list[str] | None = None) -> list[str]:
    """The buttons above the composer (Nova `replySuggestions`)."""
    found = gaps(plan, scene, settled=settled)
    out = []
    if any(g.hard for g in found):
        out.append(DRAFT_ARC)
    if any(not g.hard for g in found):
        out.append(YOU_DECIDE)
    if treatment_mode(plan) and not any(g.hard for g in found):
        out.append(PLAN_SHOTS)
    return out


def task_for(message: str, plan: dict[str, Any], scene: dict[str, Any], *,
             settled: list[str] | None = None) -> dict[str, Any] | None:
    """A suggestion's message → the task it stands for, in the conductor's shape (`{lane, tasks}`), with the soft gaps
    it settles. None: the message is not a suggestion (the router reads it)."""
    said = " ".join(message.split()).strip(" .!").lower()
    found = gaps(plan, scene, settled=settled)
    if said == DRAFT_ARC.lower():
        return {"lane": "craft", "settles": [], "tasks": [{
            "writes": ["treatment.arc"], "scope": [], "may": ["sequence.bounds", "sequence.title", "sequence.purpose"],
            "instruction": "draft the arc so that its beats cover every script block in order"}]}
    if said == YOU_DECIDE.lower():
        soft = [g for g in found if not g.hard]
        if not soft:
            return None
        return {"lane": "craft", "settles": [g.effect for g in soft], "tasks": [{
            "writes": [g.effect for g in soft], "scope": [],
            "instruction": "the director hands these over to you: write " + ", ".join(g.label for g in soft)
                           + ", in the scene's own spirit"}]}
    return None
