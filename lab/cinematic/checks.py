"""The checks and the craft measures (plan/2026-11-06 §5). No model, no network.

    hard(scene, plan)               [Problem]   the existing David checks, plus the lab's own (below). A fault is a wrong plan.
    measures(reading, plan)         [Measure]   craft, reported and never blocking: a person judges taste.

The lab's own hard checks: a beat that says someone speaks in a shot with no line (finding F8), `use_s` out of range or
below what a line needs, a shot in no sequence or sequences that do not match the shots, a colour script that misses a
sequence. The craft measures read the plan with simple rules (a size list, a name in the subjects, a word in the text):
they are a prompt for the reader's eye, not a verdict.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Literal

from pydantic import BaseModel

from contracts.david import checks as david_checks
from contracts.david.checks import code, free_text, mentions
from contracts.david.plan import Problem, norm
from contracts.david.scene import SceneS, items_of, need_s, plain_name

from .pack import Reading, is_heard, is_voice_over
from .schema import CLOSE, CinemaShotW, CinemaWire

# Someone SPEAKS: said in an action field, where only a line may be spoken. Not "answers" (answering a phone is an act).
SPEAKS = re.compile(r"\b(speaks?|speaking|says?|saying|asks?|replies|replying|shouts?|whispers?|talks?|tells?|murmurs?|"
                    r"calls? out)\b", re.IGNORECASE)
WIDE_SIZES = ("EWS", "WIDE")
OBJECT_SIZES = ("INSERT", "ECU", "POV")


class Measure(BaseModel):
    key: str
    label: str
    status: Literal["met", "missed", "info"]
    detail: str


# ── the hard checks ──────────────────────────────────────────────────────────────────────────────


def _problem(code_: str, sentence: str, shots: list[int] | None = None, key: str = "") -> Problem:
    return Problem(code=code_, sentence=sentence, shots=shots or [], fix="repair", key=key or f"{code_}:{sentence}")


def action_text(shot: CinemaShotW) -> list[str]:
    """What a shot says its people DO (beat actions and subject actions): speech has no place there."""
    ir = shot.ir
    beats = [str(b.get("action") or "") for b in ir.get("beats") or [] if isinstance(b, dict)]
    subjects = [str(s.get("action") or "") for s in ir.get("subjects") or [] if isinstance(s, dict)]
    return [*beats, *subjects]


def _speaking(plan: CinemaWire) -> list[Problem]:
    out = []
    for s in plan.shots:
        if s.lines:
            continue
        said = next((m.group(0) for t in action_text(s) if (m := SPEAKS.search(t))), "")
        if said:
            out.append(_problem("speaks", f"{code(s.n)} has no line, but a beat says someone \"{said}\": nobody speaks "
                                "in a shot with no line (Veo invents the speech). Say what they DO.", [s.n],
                                f"speaks:{s.n}"))
    return out


def _use(scene: SceneS, plan: CinemaWire) -> list[Problem]:
    out = []
    for s in plan.shots:
        if not 2 <= s.use_s <= s.take_s:
            out.append(_problem("use", f"{code(s.n)} keeps {s.use_s} s of a {s.take_s} s take: `use_s` is 2 to the "
                                "take.", [s.n], f"use:range:{s.n}"))
        lines = [i for i in items_of(scene, s.david()) if i.is_line]
        need = need_s(lines) if lines else 0.0
        if lines and s.use_s + 1e-9 < need:
            out.append(_problem("use", f"{code(s.n)} keeps {s.use_s} s, but its line needs {need:.1f} s: a line is "
                                "kept whole.", [s.n], f"use:line:{s.n}"))
    return out


def _sequences(plan: CinemaWire) -> list[Problem]:
    out = []
    if not plan.sequences:
        return [_problem("sequence", "The plan has no sequences.", key="sequence:none")]
    ids = [q.id for q in plan.sequences]
    if len(set(ids)) != len(ids):
        out.append(_problem("sequence", "Two sequences have the same id.", key="sequence:duplicate"))
    for s in plan.shots:
        if s.sequence not in ids:
            out.append(_problem("sequence", f"{code(s.n)} is in sequence \"{s.sequence}\", which does not exist.",
                                [s.n], f"sequence:unknown:{s.n}"))
    for q in plan.sequences:
        mine = [s.n for s in plan.shots if s.sequence == q.id]
        if not mine:
            out.append(_problem("sequence", f"Sequence {q.id} has no shot.", key=f"sequence:empty:{q.id}"))
        elif mine != list(range(mine[0], mine[-1] + 1)):
            out.append(_problem("sequence", f"Sequence {q.id}'s shots are not one run.", mine, f"sequence:run:{q.id}"))
        elif (q.shots.first, q.shots.last) != (mine[0], mine[-1]):
            out.append(_problem("sequence", f"Sequence {q.id} says shots {q.shots.first}-{q.shots.last}, but its "
                                f"shots are {mine[0]}-{mine[-1]}.", mine, f"sequence:span:{q.id}"))
    named = {c.sequence for c in plan.treatment.colour_script}
    for q in plan.sequences:
        if q.id not in named:
            out.append(_problem("colour", f"The colour script does not name sequence {q.id}.", key=f"colour:{q.id}"))
    for extra in sorted(named - set(ids)):
        out.append(_problem("colour", f"The colour script names sequence \"{extra}\", which does not exist.",
                            key=f"colour:unknown:{extra}"))
    if not plan.treatment.arc:
        out.append(_problem("sequence", "The treatment has no arc.", key="treatment:arc"))
    return out


def heard_names(scene: SceneS) -> list[str]:
    """People in the cast who are only a voice: they have lines, and every one is heard and not seen (a phone call).
    (`contracts.david.scene.heard_only` also asks that no action block names them, so "It is her father" hides one.)"""
    out = []
    for who in scene.cast:
        mine = [b for b in scene.lines if norm(plain_name(b.speaker)) == norm(who)]
        if mine and all(is_heard(b) for b in mine):
            out.append(who)
    return out


def _heard_in_frame(scene: SceneS, plan: CinemaWire) -> list[Problem]:
    out = []
    for who in heard_names(scene):
        for s in plan.shots:
            seen = [*(strings_of(s.ir.get("subjects"))), *strings_of(s.ir.get("first_frame"))]
            if any(mentions(t, who) for t in seen):
                out.append(_problem("heard", f"{who} is only heard (a voice on the phone) and is in {code(s.n)}'s "
                                    "subjects or first frame: take them out of the picture.", [s.n],
                                    f"heard:{s.n}:{norm(who)}"))
    return out


def strings_of(value: object) -> list[str]:
    return list(david_checks.strings(value))


def hard(scene: SceneS, plan: CinemaWire) -> list[Problem]:
    return [*david_checks.problems(scene, plan.to_david()), *_heard_in_frame(scene, plan), *_speaking(plan),
            *_use(scene, plan), *_sequences(plan)]


# ── the craft measures ───────────────────────────────────────────────────────────────────────────


def _blob(plan: CinemaWire, shot: CinemaShotW) -> str:
    return " \n ".join([*free_text(shot.david(), plan.to_david()), shot.angle, shot.lens]).lower()


def _first_subject(shot: CinemaShotW) -> str:
    subjects = shot.ir.get("subjects") or []
    if not subjects or not isinstance(subjects[0], dict):
        return ""
    return " ".join(str(v) for v in subjects[0].values())


def _is_main(shot: CinemaShotW, name: str, code_: str) -> bool:
    first = _first_subject(shot)
    return mentions(first, name) or (bool(code_) and mentions(first, code_))


def _subject_text(shot: CinemaShotW) -> str:
    return " ".join(" ".join(str(v) for v in s.values()) for s in shot.ir.get("subjects") or [] if isinstance(s, dict))


def _leads(scene: SceneS) -> list[str]:
    heard = {norm(h) for h in heard_names(scene)}
    return [c for c in scene.cast if norm(c) not in heard]


def _opens(plan: CinemaWire) -> Measure:
    first = plan.shots[:2]
    sizes = [s.size for s in first]
    ok = bool(sizes) and (sizes[0] in WIDE_SIZES or (len(sizes) > 1 and sizes[0] == "INSERT" and sizes[1] in WIDE_SIZES))
    return Measure(key="opens", label="Opens on geography (EWS/WIDE, or an INSERT that leads into one, in the first "
                   "2 shots)", status="met" if ok else "missed", detail=", ".join(f"{code(s.n)} {s.size}" for s in first))


def _intros(scene: SceneS, plan: CinemaWire, reading: Reading) -> Measure:
    codes = {str(p["name"]): str(p.get("code") or "") for p in reading.people}
    rows, missed = [], []
    for name in _leads(scene):
        shots = plan.shots
        at = next((i for i, s in enumerate(shots) if mentions(_subject_text(s), name)
                   or (codes.get(name) and mentions(_subject_text(s), codes[name]))), None)
        if at is None:
            missed.append(name)
            rows.append(f"{name}: never in a shot's subjects")
            continue
        window = shots[at:at + 3]
        hit = next((s for s in window if s.size not in WIDE_SIZES and _is_main(s, name, codes.get(name, ""))), None)
        rows.append(f"{name}: first in {code(shots[at].n)}, " + (f"main subject in {code(hit.n)} {hit.size}" if hit
                                                                  else "no close shot of them in the next 3 shots"))
        if hit is None:
            missed.append(name)
    return Measure(key="intros", label="Each lead's first appearance has a shot where they are the main subject",
                   status="missed" if missed else "met", detail="; ".join(rows))


def _objects(plan: CinemaWire, reading: Reading) -> Measure:
    wanted = reading.story_objects
    if not wanted:
        return Measure(key="objects", label="Story objects get an INSERT or ECU", status="info",
                       detail="the input names no story objects")
    rows, missed = [], []
    for obj in wanted:
        hits = [s for s in plan.shots if s.size in OBJECT_SIZES and (
            mentions(_blob(plan, s), obj) or any(norm(a.object) and obj in norm(a.object) for a in plan.added
                                                 if a.shot == s.n))]
        rows.append(f"{obj}: " + (", ".join(f"{code(s.n)} {s.size}" for s in hits) if hits else "no insert"))
        if not hits:
            missed.append(obj)
    return Measure(key="objects", label="Story objects get an INSERT or ECU", status="missed" if missed else "met",
                   detail="; ".join(rows))


def _reactions(scene: SceneS, plan: CinemaWire, reading: Reading) -> Measure:
    codes = {str(p["name"]): str(p.get("code") or "") for p in reading.people}
    leads = _leads(scene)
    covered: list[str] = []
    missed: list[str] = []
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
        (covered if listener or other else missed).append(f"{b.line_id}")
    total = len(covered) + len(missed)
    return Measure(key="reactions", label="Each line has a reaction or listener shot for the other person, within 1 "
                   "shot", status="met" if total and not missed else ("info" if not total else "missed"),
                   detail=f"{len(covered)} of {total} lines" + (f"; none for {', '.join(missed)}" if missed else ""))


COMPOUND = re.compile(r"\b(and|then)\s+\w+(?:s|es)\b", re.IGNORECASE)


def _compound(scene: SceneS, plan: CinemaWire) -> Measure:
    rows, missed = [], []
    for b in scene.blocks:
        if b.kind == "dialogue" or not COMPOUND.search(b.text):
            continue
        covering = [s.n for s in plan.shots if b.index in s.blocks]
        rows.append(f"b{b.index}: {len(covering)} shot(s)")
        if len(covering) < 2:
            missed.append(f"b{b.index}")
    return Measure(key="compound", label="Compound action blocks (two verbs or more) get more than one shot",
                   status="info" if not rows else ("missed" if missed else "met"),
                   detail="; ".join(rows) or "no compound action block", )


MOVING = re.compile(r"\b(falls?|fell|falling|drops?|dropped|tumbl\w+|slips?|slipped|spills?|spilled|shatters?|hits?|lands?|splash\w*|crash\w*|skids?|throws?|tosses|slams?|"
                    r"runs?|running|hurr\w+|rush\w*|chas\w+|race[sd]?|darts?|bolts?|storms?)\b", re.IGNORECASE)
NEGATED = re.compile(r"\b(?:no|not|never|without|doesn['\u2019]t|don['\u2019]t|didn['\u2019]t|won['\u2019]t|can['\u2019]t)\s+(?:\w+\s+)?\w+", re.IGNORECASE)
BODY_DROP = re.compile(r"\b(?:gaze|eyes?|voice|shoulders?|head|smile|face|look|glance|breath)\s+(?:\w+\s+)?(?:drops?|falls?|slips?)\b", re.IGNORECASE)  # a gaze or a voice that drops is not an object that falls
LOCKED = re.compile(r"\b(locked|static|still|fixed|tripod|no movement)\b", re.IGNORECASE)
FOLLOWS = re.compile(r"\b(follow\w*|track\w*|pan\w*|tilt\w*|push\w*|pull\w*|drift\w*|dolly\w*|crane|handheld|"
                     r"whip\w*|sidestep|scoop\w*|sweep\w*|arc\w*|orbit\w*)\b", re.IGNORECASE)
WIDES = {"WIDE", "EWS"}  # a wide may stay still while people cross it: a static composition is a choice


def _motion(plan: CinemaWire) -> Measure:
    """Motion follows meaning (a general craft rule): a shot of something falling or racing is not locked off. Only a real fall
    or a rush counts (a negated verb, a small gesture and a wide that stays still do not)."""
    moving, locked = [], []
    for s in plan.shots:
        acts = " ".join(str(b.get("action") or "") for b in s.ir.get("beats") or [] if isinstance(b, dict))
        if s.size in WIDES or not MOVING.search(BODY_DROP.sub(" ", NEGATED.sub(" ", acts))):
            continue
        moving.append(s.n)
        move = str((s.ir.get("cinematography") or {}).get("movement") or "")
        if LOCKED.search(move) and not FOLLOWS.search(move):
            locked.append(s.n)
    return Measure(key="motion", label="Motion follows meaning: a shot of something falling or racing is not locked off",
                   status="info" if not moving else ("missed" if locked else "met"),
                   detail=(f"{len(moving)} shot(s) of a fall or a rush" + (f"; locked off: {', '.join(code(n) for n in locked)}" if locked else "")))


def _variety(plan: CinemaWire) -> Measure:
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


def _grade(plan: CinemaWire) -> Measure:
    grades = [norm(c.grade) for c in plan.treatment.colour_script]
    return Measure(key="grade", label="The grade moves at least once across sequences",
                   status="met" if len(set(grades)) > 1 else "missed",
                   detail=" → ".join(f"{c.sequence}: {c.grade}" for c in plan.treatment.colour_script))


def _endings(scene: SceneS, plan: CinemaWire) -> Measure:
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


def _totals(plan: CinemaWire, reading: Reading) -> Measure:
    take, use = sum(s.take_s for s in plan.shots), sum(s.use_s for s in plan.shots)
    guide = reading.guide_s
    return Measure(key="totals", label="Shots, take seconds and use seconds against the guide", status="info",
                   detail=f"{len(plan.shots)} shots, {take} s of takes, {use} s kept" +
                          (f" against a guide of {guide:g} s ({use - guide:+.0f} s)" if guide else ""))


def _additions(plan: CinemaWire) -> Measure:
    kinds = Counter(a.kind for a in plan.added)
    return Measure(key="additions", label="Additions: count and kinds", status="info",
                   detail=f"{len(plan.added)}" + (f" ({', '.join(f'{k} {v}' for k, v in kinds.most_common())})"
                                                  if kinds else ""))


def measures(reading: Reading, plan: CinemaWire) -> list[Measure]:
    scene = reading.scene
    if not plan.shots:
        return []
    return [_opens(plan), _intros(scene, plan, reading), _objects(plan, reading), _reactions(scene, plan, reading),
            _compound(scene, plan), _motion(plan), _variety(plan), _grade(plan), _endings(scene, plan), _totals(plan, reading),
            _additions(plan)]


def seconds(value: float) -> int:
    """Whole seconds that hold `value` (a line's need, rounded up)."""
    return math.ceil(value - 1e-9)
