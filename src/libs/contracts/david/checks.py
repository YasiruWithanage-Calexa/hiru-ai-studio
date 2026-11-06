"""Code judges facts (plan/2026-11-05e §6): every check on a David plan, as pure functions.

    problems(scene, plan, removed=…)   → [Problem]   every failure as an exact sentence, with who fixes it

A check never changes the plan and never asks a model. `fix` says who deals with a problem: `mend` (code, in
`david_mend`), `repair` (the author, shown exactly this sentence), `drop` (an addition code removes and reports) or
`report` (shown to a person, never sent back). Shots are named `S01`, blocks `b3`, lines `L4`, as the author sees them.
"""
from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from itertools import pairwise
from typing import Any

from contracts import stagemap
from contracts.david.plan import NEEDS_OBJECT, NEEDS_WHO, TAKES, Problem, norm
from contracts.david.scene import (
    SceneS,
    heard_only,
    items_of,
    need_s,
    plain_name,
    shortest_take,
    speech_in,
    split_items,
)
from contracts.david.stored import after_block
from contracts.david.wire import AddedW, DavidWire, EndStateW, ShotW
from contracts.shotplan import ProposedShot
from contracts.shotplan import fit as fit_kernel
from contracts.timing import speech_seconds, words_in
from contracts.veo import VEO_DURATIONS

S = "S{:02d}"


def code(n: int) -> str:
    return S.format(n)


def strings(value: Any) -> Iterator[str]:
    """Every string in a nested value (the free text of an IR)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def free_text(shot: ShotW, plan: DavidWire) -> list[str]:
    """Everything the author wrote in words for a shot."""
    own = [a.what for a in plan.added if a.shot == shot.n]
    return [*strings(shot.ir), shot.why, shot.sound.ambience, shot.sound.effects, shot.sound.music, *own]


def mentions(text: str, name: str) -> bool:
    """`name` appears in `text` as a whole word, ignoring case."""
    return bool(name.strip()) and re.search(rf"(?<!\w){re.escape(name.strip())}(?!\w)", text, re.IGNORECASE) is not None


def head(text: str, n: int = 6) -> str:
    return " ".join(text.split()[:n])


# ── the addition rule (also used by `david_mend`, which drops what fails) ────────────────────────


def addition_fault(scene: SceneS, plan: DavidWire, added: AddedW, removed: Sequence[tuple[str, int]] = ()) -> str:
    """Why an addition is refused, as a sentence; "" when it stands. `removed`: (kind, after_block) of additions a
    person took out before: they never come back."""
    cast = {norm(c) for c in scene.cast}
    where = code(added.shot)
    if plan.shot(added.shot) is None:
        return f"An addition names shot {added.shot}, which the plan does not have."
    if (norm(added.kind), after_block(plan, added.shot)) in {(norm(k), b) for k, b in removed}:
        return f"{where}: a {added.kind} a person removed before ({head(added.what)}) came back."
    if added.kind in NEEDS_WHO:
        if not added.who:
            return f"{where}: a {added.kind} must name who it shows."
        stranger = next((w for w in added.who if norm(w) not in cast), "")
        if stranger:
            return f"{where}: the {added.kind} shows {stranger}, who is not in this scene."
    if added.kind in NEEDS_OBJECT:
        if not added.object.strip():
            return f"{where}: a {added.kind} must name its object."
        if not scene.fits(added.object):
            return f"{where}: the {added.kind} shows {added.object}, which the script and the place do not have."
    return ""


# ── the checks ───────────────────────────────────────────────────────────────────────────────────


def problems(scene: SceneS, plan: DavidWire, removed: Sequence[tuple[str, int]] = ()) -> list[Problem]:
    out: list[Problem] = []
    if not plan.shots:
        return [Problem(code="shape", sentence="The plan has no shots.", fix="repair", key="shape:empty")]
    out += _shape(plan)
    out += _blocks_and_lines(scene, plan)
    out += _clock(scene, plan)
    out += _added(scene, plan, removed)
    out += _names(scene, plan)
    out += _speech(scene, plan)
    out += _staging(scene, plan)
    out += _heard(scene, plan)
    out += _feasibility(plan)
    out += _end_state(scene, plan)
    return out


def _shape(plan: DavidWire) -> list[Problem]:
    out = []
    numbers = [s.n for s in plan.shots]
    if numbers != list(range(1, len(numbers) + 1)):
        out.append(Problem(code="shape", sentence="The shots are not numbered 1.. in the order they play.",
                           fix="mend", key="shape:numbers"))
    for s in plan.shots:
        if s.take_s not in TAKES:
            out.append(Problem(code="shape", sentence=f"{code(s.n)} is a {s.take_s} s take; Veo makes "
                               f"{', '.join(str(t) for t in TAKES)} s.", shots=[s.n], fix="repair",
                               key=f"shape:take:{s.n}"))
    return out


def _blocks_and_lines(scene: SceneS, plan: DavidWire) -> list[Problem]:
    out: list[Problem] = []
    known = {b.index for b in scene.blocks}
    shown: dict[int, list[int]] = {}
    for s in plan.shots:
        stray = sorted(set(s.blocks) - known)
        if stray:
            out.append(Problem(code="blocks", sentence=f"{code(s.n)} shows block {', '.join(f'b{b}' for b in stray)}, "
                               "which the scene does not have.", shots=[s.n], key=f"blocks:unknown:{s.n}"))
        run = sorted(set(s.blocks) & known)
        if run and run != list(range(run[0], run[-1] + 1)):
            out.append(Problem(code="blocks", sentence=f"{code(s.n)} shows blocks {', '.join(f'b{b}' for b in run)}, "
                               "which are not one run: a shot shows blocks that follow each other (give the others "
                               "their own shot).", shots=[s.n], key=f"blocks:run:{s.n}"))
        for index in run:
            shown.setdefault(index, []).append(s.n)
    for b in sorted(scene.blocks, key=lambda x: x.index):
        if b.index not in shown:
            what = f"line {b.line_id}" if b.line_id else b.kind
            out.append(Problem(code="blocks", sentence=f"Block b{b.index} ({what}: \"{head(b.text)}\") is shown by no "
                               "shot: give it a shot, or add it to one.", key=f"blocks:missing:{b.index}"))
    starts = [(s.n, min(s.blocks)) for s in plan.shots if s.blocks]
    for (a, first_a), (after, first_b) in pairwise(starts):
        if first_b < first_a:
            out.append(Problem(code="blocks", shots=[a, after], key=f"blocks:order:{a}:{after}",
                               sentence=f"{code(after)} starts at b{first_b}, before {code(a)} (b{first_a}): shots "
                                        "play in script order."))
    # lines
    seen: dict[str, list[int]] = {}
    for s in plan.shots:
        for ln in s.lines:
            seen.setdefault(ln, []).append(s.n)
    for ln, where in seen.items():
        block = scene.line_block(ln)
        if block is None:
            out.append(Problem(code="lines", sentence=f"{code(where[0])} names line {ln}, which the scene does not "
                               "have.", shots=where[:1], key=f"lines:unknown:{ln}"))
            continue
        if len(where) > 1:
            out.append(Problem(code="lines", sentence=f"Line {ln} is used in {', '.join(code(n) for n in where)}: a "
                               "line is spoken in one shot only.", shots=where, key=f"lines:twice:{ln}"))
        for n in where:
            shot = plan.shot(n)
            if shot is not None and block.index not in shot.blocks:
                out.append(Problem(code="lines", sentence=f"{code(n)} carries line {ln}, but does not show its block "
                                   f"b{block.index}: add b{block.index} to its blocks.", shots=[n],
                                   key=f"lines:block:{ln}:{n}"))
    for b in scene.lines:
        assert b.line_id
        if b.line_id not in seen:
            words = words_in(b.text)
            out.append(Problem(code="lines", sentence=f"Line {b.line_id} ({b.speaker}, {words} words, "
                               f"{speech_seconds(words, b.delivery):.1f} s) is spoken in no shot.",
                               key=f"lines:missing:{b.line_id}"))
    order = [ln for s in plan.shots for ln in s.lines if scene.line_block(ln) is not None]
    wanted = [b.line_id for b in sorted(scene.lines, key=lambda x: x.index) if b.line_id in order]
    firsts = list(dict.fromkeys(order))
    if firsts != wanted and len(set(order)) == len(order):
        out.append(Problem(code="lines", sentence="The lines are spoken out of script order: "
                           f"{', '.join(firsts)} (the script has {', '.join(wanted)}).", key="lines:order"))
    for b in scene.lines:  # a dialogue block in two shots is spoken twice
        holders = shown.get(b.index, [])
        if len(holders) > 1 and b.line_id:
            out.append(Problem(code="blocks", sentence=f"Block b{b.index} (line {b.line_id}) is in "
                               f"{', '.join(code(n) for n in holders)}: a dialogue block belongs to one shot.",
                               shots=holders, key=f"blocks:dialogue:{b.index}"))
        elif holders and b.line_id:
            shot = plan.shot(holders[0])
            if shot is not None and b.line_id not in shot.lines:
                out.append(Problem(code="blocks", sentence=f"{code(holders[0])} shows b{b.index} but does not list "
                                   f"line {b.line_id}: say who speaks it here.", shots=[holders[0]],
                                   key=f"blocks:unlisted:{b.index}"))
    cast = {norm(c) for c in scene.cast}
    for s in plan.shots:
        if not s.over:
            continue
        speakers = {norm(plain_name(spoken.speaker)) for ln in s.lines if (spoken := scene.line_block(ln))}
        if not s.lines:
            out.append(Problem(code="lines", sentence=f"{code(s.n)} is shot over {s.over} but carries no line.",
                               shots=[s.n], key=f"lines:over:{s.n}"))
        elif norm(s.over) not in cast or norm(s.over) in speakers:
            out.append(Problem(code="lines", sentence=f"{code(s.n)} plays a line over {s.over}: it must be over a "
                               "person present who is not the speaker.", shots=[s.n], key=f"lines:listener:{s.n}"))
    return out


def _clock(scene: SceneS, plan: DavidWire) -> list[Problem]:
    out = []
    for s in plan.shots:
        items = items_of(scene, s)
        need = need_s(items)
        if need <= s.take_s + 1e-9:
            continue
        longest = max(VEO_DURATIONS)
        if shortest_take(need):
            out.append(Problem(code="clock", sentence=f"{code(s.n)} needs {need:.1f} s to show what it holds; it is a "
                               f"{s.take_s} s take (a {shortest_take(need)} s take holds it).", shots=[s.n],
                               fix="mend", key=f"clock:{s.n}"))
        elif len(split_items(items, longest)) > 1:
            out.append(Problem(code="clock", sentence=f"{code(s.n)} needs {need:.1f} s, more than the longest take "
                               f"({longest} s): it is split at a block boundary.", shots=[s.n], fix="mend",
                               key=f"clock:{s.n}"))
        else:
            out.append(Problem(code="clock", sentence=f"{code(s.n)} needs {need:.1f} s and cannot be cut: one line or "
                               f"one action is longer than the longest take ({longest} s). It is reported, never "
                               "trimmed.", shots=[s.n], fix="report", key=f"clock:{s.n}"))
    return out


def _added(scene: SceneS, plan: DavidWire, removed: Sequence[tuple[str, int]]) -> list[Problem]:
    out = []
    listed = {a.shot for a in plan.added}
    for a in plan.added:
        why = addition_fault(scene, plan, a, removed)
        if why:
            out.append(Problem(code="added", sentence=why + " It is dropped.", shots=[a.shot] if plan.shot(a.shot)
                               else [], fix="drop", key=f"added:{a.shot}:{a.kind}"))
    for s in plan.shots:
        if not s.blocks and not s.lines and s.n not in listed:
            out.append(Problem(code="added", sentence=f"{code(s.n)} shows no script block and is not listed in "
                               "`added`: list it with its kind, or give it blocks.", shots=[s.n],
                               key=f"added:unlisted:{s.n}"))
    return out


def _names(scene: SceneS, plan: DavidWire) -> list[Problem]:
    out = []
    cast = {norm(c) for c in scene.cast}
    strangers = [n for n in scene.others if norm(n) not in cast]
    texts = {s.n: free_text(s, plan) for s in plan.shots}
    texts[0] = [plan.notes]
    for n, parts in texts.items():
        blob = " \n ".join(parts)
        for name in strangers:
            if mentions(blob, name):
                where = "The notes name" if n == 0 else f"{code(n)} names"
                out.append(Problem(code="names", sentence=f"{where} {name}, who is not in this scene.",
                                   shots=[n] if n else [], key=f"names:{n}:{norm(name)}"))
    return out


def _speech(scene: SceneS, plan: DavidWire) -> list[Problem]:
    out = []
    for s in plan.shots:
        if any(speech_in(t, scene.lines) for t in free_text(s, plan)):
            out.append(Problem(code="speech", sentence=f"{code(s.n)} has quoted speech or a line's words in its "
                               "free text; they are removed (a line reaches the prompt only as the script's).",
                               shots=[s.n], fix="mend", key=f"speech:{s.n}"))
    return out


def stage_map(scene: SceneS, plan: DavidWire) -> stagemap.SceneStaging:
    """The author's staging as a validated map: an entry that is not true to this scene is dropped."""
    raw = {"zones": plan.staging.zones, "marks": [m.model_dump() for m in plan.staging.marks]}
    return stagemap.validate(raw, scene.items(), scene.cast, version=1, by="model")


def _staging(scene: SceneS, plan: DavidWire) -> list[Problem]:
    staging = stage_map(scene, plan)
    if not staging.marks:
        return [Problem(code="staging", sentence="The staging map has fewer than two spots or no marks, so teleports, "
                        "crossed lines and eyelines cannot be checked.", fix="report", key="staging:none")]
    proposals: list[tuple[int, ProposedShot]] = []
    for s in plan.shots:
        known = sorted(set(s.blocks) & {b.index for b in scene.blocks})
        if known:
            proposals.append((s.n, ProposedShot(known[0], known[-1] + 1, s.size, "", None, s.take_s, True, s.link)))
    if not proposals:
        return []
    proposals.sort(key=lambda p: (p[1].start, p[1].end))
    result = fit_kernel(scene.items(), [p for _, p in proposals], envelope_s=int(scene.envelope_s or 9999))
    numbers = [n for n, _ in proposals]
    out = []
    for f in stagemap.checks(staging, scene.items(), result, scene.cast):
        shot = numbers[f.shot - 1] if f.shot and 0 < f.shot <= len(numbers) else None
        out.append(Problem(code="staging", sentence=f.message, shots=[shot] if shot else [], fix="repair",
                           key=f"staging:{f.code}:{f.block}:{shot}:{','.join(f.who)}"))
    return out


def _heard(scene: SceneS, plan: DavidWire) -> list[Problem]:
    out = []
    for who in heard_only(scene):
        for s in plan.shots:
            seen = [t for t in strings({"subjects": s.ir.get("subjects"), "first_frame": s.ir.get("first_frame")})]
            if any(mentions(t, who) for t in seen):
                out.append(Problem(code="heard", sentence=f"{who} is only heard (a voice on the phone or off screen) "
                                   f"and is in {code(s.n)}'s subjects or first frame: take them out of the picture.",
                                   shots=[s.n], key=f"heard:{s.n}:{norm(who)}"))
    return out


# What Veo does badly, and the known way round it (plan §6 "feasibility": reported, not repaired, in the first version)
FEASIBILITY: tuple[tuple[str, str, str], ...] = (
    ("screen text", r"\b(reads?|text on|the screen shows|message (?:says|reads)|caption|subtitle|sign (?:says|reads)|"
     r"lettering|notification)\b", "Veo cannot render readable text: show the glow of the screen on a face and let "
     "a line or a sound carry the words."),
    ("a mirror", r"\b(mirror|reflection)\b", "Veo breaks reflections: shoot the person, not the glass."),
    ("fast hands", r"\b(typing|texting|rapid(?:ly)?|dialling|dialing|shuffl\w+|juggl\w+|knitting|sewing)\b",
     "fast finger work blurs: hold on the face, or show the hands still on the object."),
    ("touching", r"\b(hug\w*|embrac\w+|kiss\w*|holds? hands|holding hands)\b", "bodies in contact merge: keep a "
     "hand's width apart, or cut away at the moment of contact."),
    ("a crowd", r"\b(crowd|dozens|hundreds|packed with people|mob)\b", "Veo invents the crowd's faces: frame a few "
     "people near, the rest soft and far."),
)


def _feasibility(plan: DavidWire) -> list[Problem]:
    out = []
    for s in plan.shots:
        blob = " \n ".join(free_text(s, plan))
        for name, pattern, fix in FEASIBILITY:
            if re.search(pattern, blob, re.IGNORECASE):
                out.append(Problem(code="feasibility", sentence=f"{code(s.n)} asks for {name}. {fix}", shots=[s.n],
                                   fix="report", key=f"feasibility:{s.n}:{name}"))
    return out


def _end_state(scene: SceneS, plan: DavidWire) -> list[Problem]:
    es: EndStateW = plan.end_state
    cast = {norm(c): c for c in scene.cast}
    out = []
    named = set()
    for p in es.people:
        named.add(norm(p.who))
        if norm(p.who) not in cast:
            out.append(Problem(code="end_state", sentence=f"The end state names {p.who}, who is not in this scene.",
                               key=f"end_state:stranger:{norm(p.who)}"))
    for key, name in cast.items():
        if key not in named:
            out.append(Problem(code="end_state", sentence=f"The end state does not say where {name} is.",
                               key=f"end_state:missing:{key}"))
    staging = stage_map(scene, plan)
    last = max((b.index for b in scene.blocks), default=0)
    props = {norm(x.what) for x in es.props}
    for p in es.people:
        mark = staging.mark_at(scene.items(), p.who, last) if staging.marks else None
        if mark is None:
            continue
        here = norm(p.where)
        if mark.zone != stagemap.OFF and norm(mark.zone) not in here and here not in norm(mark.zone):
            out.append(Problem(code="end_state", sentence=f"The staging ends {p.who} at the {mark.zone}, but the end "
                               f"state puts {p.who} at \"{p.where}\".", key=f"end_state:where:{norm(p.who)}"))
        held = norm(mark.holding)
        if held and held not in norm(p.holding) and held not in props:
            out.append(Problem(code="end_state", sentence=f"{p.who} is holding {mark.holding} at the end of the "
                               "staging, but the end state loses it.", key=f"end_state:holding:{norm(p.who)}"))
    return out


def repairable(found: list[Problem]) -> list[Problem]:
    """What the author is asked to fix."""
    return [p for p in found if p.fix == "repair"]
