"""The craft measures (plan/2026-11-06b §5, from the cinematic lab's `checks.measures`). No model, no network.

    measures(scene, plan, craft)   [Measure]   craft, reported and never blocking: a person judges taste

A measure reads the plan with a simple rule (a size list, a name in the subjects, a word in the text). It is a prompt
for
the eye, not a verdict, and it never fails a plan. A MISSED measure is a craft gap: the stabiliser sends it back to the
author with the hard faults, so the author can improve it where the scene allows (`systems/jonathan`).

`Craft` is what the measures need besides the scene and the plan: each person's code (a subject may name them by it),
the
scene's story objects (the production's props the script names: the lab listed them by hand), and the length guide.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict

from contracts.jonathan.checks import code, free_text, mentions
from contracts.jonathan.plan import norm
from contracts.jonathan.scene import SceneS, heard_names, is_voice_over
from contracts.jonathan.wire import CLOSE, JonathanWire, ShotW

WIDE_SIZES = ("EWS", "WIDE")
OBJECT_SIZES = ("INSERT", "ECU", "POV")


class Measure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    status: Literal["met", "missed", "info"]
    detail: str


class Craft(BaseModel):
    """What the measures read besides the scene and the plan."""

    model_config = ConfigDict(extra="forbid")

    codes: dict[str, str] = {}  # a person's name -> their code (C01)
    story_objects: list[str] = []  # the objects the story turns on: each wants a close shot
    guide_s: float = 0.0  # the length guide (the scene's envelope), 0 = none


def missed(found: list[Measure]) -> list[Measure]:
    return [m for m in found if m.status == "missed"]


def _blob(plan: JonathanWire, shot: ShotW) -> str:
    return " \n ".join([*free_text(shot, plan), shot.angle, shot.lens]).lower()


def _first_subject(shot: ShotW) -> str:
    subjects = shot.ir.get("subjects") or []
    if not subjects or not isinstance(subjects[0], dict):
        return ""
    return " ".join(str(v) for v in subjects[0].values())


def _is_main(shot: ShotW, name: str, code_: str) -> bool:
    first = _first_subject(shot)
    return mentions(first, name) or (bool(code_) and mentions(first, code_))


def _subject_text(shot: ShotW) -> str:
    return " ".join(" ".join(str(v) for v in s.values()) for s in shot.ir.get("subjects") or [] if isinstance(s, dict))


def _leads(scene: SceneS) -> list[str]:
    heard = {norm(h) for h in heard_names(scene)}
    return [c for c in scene.cast if norm(c) not in heard]


def _opens(plan: JonathanWire) -> Measure:
    first = plan.shots[:2]
    sizes = [s.size for s in first]
    leads_in = len(sizes) > 1 and sizes[0] == "INSERT" and sizes[1] in WIDE_SIZES  # a detail that opens out
    ok = bool(sizes) and (sizes[0] in WIDE_SIZES or leads_in)
    return Measure(key="opens", label="Opens on geography (EWS/WIDE, or an INSERT that leads into one, in the first "
                   "2 shots)", status="met" if ok else "missed",
                   detail=", ".join(f"{code(s.n)} {s.size}" for s in first))


def _intros(scene: SceneS, plan: JonathanWire, craft: Craft) -> Measure:
    codes = craft.codes
    rows, gaps = [], []
    for name in _leads(scene):
        shots = plan.shots
        at = next((i for i, s in enumerate(shots) if mentions(_subject_text(s), name)
                   or (codes.get(name) and mentions(_subject_text(s), codes[name]))), None)
        if at is None:
            gaps.append(name)
            rows.append(f"{name}: never in a shot's subjects")
            continue
        window = shots[at:at + 3]
        hit = next((s for s in window if s.size not in WIDE_SIZES and _is_main(s, name, codes.get(name, ""))), None)
        rows.append(f"{name}: first in {code(shots[at].n)}, " + (f"main subject in {code(hit.n)} {hit.size}" if hit
                                                                  else "no close shot of them in the next 3 shots"))
        if hit is None:
            gaps.append(name)
    return Measure(key="intros", label="Each lead's first appearance has a shot where they are the main subject",
                   status="missed" if gaps else "met", detail="; ".join(rows))


def _objects(plan: JonathanWire, craft: Craft) -> Measure:
    wanted = craft.story_objects
    if not wanted:
        return Measure(key="objects", label="Story objects get an INSERT or ECU", status="info",
                       detail="the scene names no story objects")
    rows, gaps = [], []
    for obj in wanted:
        hits = [s for s in plan.shots if s.size in OBJECT_SIZES and (
            mentions(_blob(plan, s), obj) or any(norm(a.object) and norm(obj) in norm(a.object) for a in plan.added
                                                 if a.shot == s.n))]
        rows.append(f"{obj}: " + (", ".join(f"{code(s.n)} {s.size}" for s in hits) if hits else "no insert"))
        if not hits:
            gaps.append(obj)
    return Measure(key="objects", label="Story objects get an INSERT or ECU", status="missed" if gaps else "met",
                   detail="; ".join(rows))


def _reactions(scene: SceneS, plan: JonathanWire, craft: Craft) -> Measure:
    codes = craft.codes
    leads = _leads(scene)
    covered: list[str] = []
    gaps: list[str] = []
    for b in scene.lines:
        if is_voice_over(b):
            continue  # a thought or a narrator: nobody reacts to it
        holder = next((s for s in plan.shots if b.line_id in s.lines), None)
        if holder is None:
            continue
        speaker = next((n for n in leads if norm(n) == norm(b.speaker)), "")
        near = [s for s in plan.shots if abs(s.n - holder.n) <= 1]
        listener = bool(holder.over) or any(a.kind in ("reaction", "listener") and abs(a.shot - holder.n) <= 1
                                            for a in plan.added)
        other = any(s.n != holder.n and any(n != speaker and _is_main(s, n, codes.get(n, "")) for n in leads)
                    and not s.lines for s in near)
        (covered if listener or other else gaps).append(f"{b.line_id}")
    total = len(covered) + len(gaps)
    return Measure(key="reactions", label="Each line has a reaction or listener shot for the other person, within 1 "
                   "shot", status="met" if total and not gaps else ("info" if not total else "missed"),
                   detail=f"{len(covered)} of {total} lines" + (f"; none for {', '.join(gaps)}" if gaps else ""))


COMPOUND = re.compile(r"\b(and|then)\s+\w+(?:s|es)\b", re.IGNORECASE)


def _compound(scene: SceneS, plan: JonathanWire) -> Measure:
    rows, gaps = [], []
    for b in scene.blocks:
        if b.kind == "dialogue" or not COMPOUND.search(b.text):
            continue
        covering = [s.n for s in plan.shots if b.index in s.blocks]
        rows.append(f"b{b.index}: {len(covering)} shot(s)")
        if len(covering) < 2:
            gaps.append(f"b{b.index}")
    return Measure(key="compound", label="Compound action blocks (two verbs or more) get more than one shot",
                   status="info" if not rows else ("missed" if gaps else "met"),
                   detail="; ".join(rows) or "no compound action block")


MOVING = re.compile(r"\b(falls?|fell|falling|drops?|dropped|tumbl\w+|slips?|slipped|spills?|spilled|shatters?|hits?|"
                    r"lands?|splash\w*|crash\w*|skids?|throws?|tosses|slams?|"
                    r"runs?|running|hurr\w+|rush\w*|chas\w+|race[sd]?|darts?|bolts?|storms?)\b", re.IGNORECASE)
NEGATED = re.compile(r"\b(?:no|not|never|without|doesn['’]t|don['’]t|didn['’]t|won['’]t|"
                     r"can['’]t)\s+(?:\w+\s+)?\w+", re.IGNORECASE)
# a gaze or a voice that drops is not an object that falls
BODY_DROP = re.compile(r"\b(?:gaze|eyes?|voice|shoulders?|head|smile|face|look|glance|breath)\s+(?:\w+\s+)?"
                       r"(?:drops?|falls?|slips?)\b", re.IGNORECASE)
LOCKED = re.compile(r"\b(locked|static|still|fixed|tripod|no movement)\b", re.IGNORECASE)
FOLLOWS = re.compile(r"\b(follow\w*|track\w*|pan\w*|tilt\w*|push\w*|pull\w*|drift\w*|dolly\w*|crane|handheld|"
                     r"whip\w*|sidestep|scoop\w*|sweep\w*|arc\w*|orbit\w*)\b", re.IGNORECASE)


def _motion(plan: JonathanWire) -> Measure:
    """Motion follows meaning (a general craft rule): a shot of something falling or racing is not locked off. Only a
    real
    fall or a rush counts (a negated verb, a small gesture and a wide that stays still do not)."""
    moving, locked = [], []
    for s in plan.shots:
        acts = " ".join(str(b.get("action") or "") for b in s.ir.get("beats") or [] if isinstance(b, dict))
        if s.size in WIDE_SIZES or not MOVING.search(BODY_DROP.sub(" ", NEGATED.sub(" ", acts))):
            continue
        moving.append(s.n)
        move = str((s.ir.get("cinematography") or {}).get("movement") or "")
        if LOCKED.search(move) and not FOLLOWS.search(move):
            locked.append(s.n)
    return Measure(key="motion",
                   label="Motion follows meaning: a shot of something falling or racing is not locked off",
                   status="info" if not moving else ("missed" if locked else "met"),
                   detail=f"{len(moving)} shot(s) of a fall or a rush"
                          + (f"; locked off: {', '.join(code(n) for n in locked)}" if locked else ""))


def _variety(plan: JonathanWire) -> Measure:
    sizes = Counter(s.size for s in plan.shots)
    close = [s for s in plan.shots if s.size in CLOSE]
    turns = []
    for s in close:
        at = next((a.beat for a in plan.treatment.arc if s.blocks and a.blocks.first <= min(s.blocks) <= a.blocks.last),
                  "")
        turns.append(f"{code(s.n)} {s.size}" + (f" at \"{at}\"" if at else ""))
    ok = len(sizes) >= 5 and bool(close)
    return Measure(key="variety", label="Size variety (5 sizes or more) and the closest sizes at the arc's turns",
                   status="met" if ok else "missed",
                   detail=f"{len(sizes)} sizes ({', '.join(f'{k} {v}' for k, v in sizes.most_common())}); closest: "
                          + ("; ".join(turns) or "none"))


def _grade(plan: JonathanWire) -> Measure:
    grades = [norm(c.grade) for c in plan.treatment.colour_script]
    return Measure(key="grade", label="The grade moves at least once across sequences",
                   status="met" if len(set(grades)) > 1 else "missed",
                   detail=" → ".join(f"{c.sequence}: {c.grade}" for c in plan.treatment.colour_script))


def _endings(scene: SceneS, plan: JonathanWire) -> Measure:
    held, rows = 0, []
    for q in plan.sequences:
        mine = [s for s in plan.shots if s.sequence == q.id]
        if not mine:
            continue
        last = mine[-1]
        ok = not last.over and all(is_voice_over(b) for ln in last.lines if (b := scene.line_block(ln)))
        held += ok
        rows.append(f"{q.id}: {code(last.n)} {last.size}" + ("" if ok else " (ends on a line)"))
    return Measure(key="endings", label="Each sequence ends on a held image (no line, or a voice over the picture)",
                   status="met" if rows and held == len(rows) else "missed", detail="; ".join(rows))


def _totals(plan: JonathanWire, craft: Craft) -> Measure:
    take, use = sum(s.take_s for s in plan.shots), sum(s.use_s for s in plan.shots)
    guide = craft.guide_s
    return Measure(key="totals", label="Shots, take seconds and use seconds against the guide", status="info",
                   detail=f"{len(plan.shots)} shots, {take} s of takes, {use} s kept"
                          + (f" against a guide of {guide:g} s ({use - guide:+.0f} s)" if guide else ""))


def _additions(plan: JonathanWire) -> Measure:
    kinds = Counter(a.kind for a in plan.added)
    return Measure(key="additions", label="Additions: count and kinds", status="info",
                   detail=f"{len(plan.added)}" + (f" ({', '.join(f'{k} {v}' for k, v in kinds.most_common())})"
                                                  if kinds else ""))


def measures(scene: SceneS, plan: JonathanWire, craft: Craft | None = None) -> list[Measure]:
    craft = craft or Craft()
    if not plan.shots:
        return []
    return [_opens(plan), _intros(scene, plan, craft), _objects(plan, craft), _reactions(scene, plan, craft),
            _compound(scene, plan), _motion(plan), _variety(plan), _grade(plan), _endings(scene, plan),
            _totals(plan, craft), _additions(plan)]
