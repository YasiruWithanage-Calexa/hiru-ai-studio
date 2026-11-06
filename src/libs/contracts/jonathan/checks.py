"""Code judges facts (plan/2026-11-06b §5): every hard check on a Jonathan plan, as pure functions.

    problems(scene, plan, removed=…)   → [Problem]   every failure as an exact sentence, with who fixes it

A check never changes the plan and never asks a model. `fix` says who deals with a problem: `mend` (code, in
`jonathan_mend`), `repair` (the author, shown exactly this sentence), `drop` (an addition code removes and reports) or
`report` (shown to a person, never sent back). Shots are named `S01`, blocks `b3`, lines `L4`, as the author sees them.
"""
from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from itertools import pairwise
from typing import Any

from contracts import stagemap
from contracts.holding import Ledger, thing_of
from contracts.jonathan.plan import NEEDS_OBJECT, NEEDS_WHO, TAKES, Problem, norm
from contracts.jonathan.scene import (
    SceneS,
    heard_names,
    heard_only,
    items_of,
    need_s,
    plain_name,
    shortest_take,
    speech_in,
    split_items,
)
from contracts.jonathan.stored import after_block
from contracts.jonathan.wire import AddedW, EndStateW, JonathanWire, ShotW
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


def free_text(shot: ShotW, plan: JonathanWire) -> list[str]:
    """Everything the author wrote in words for a shot."""
    own = [a.what for a in plan.added if a.shot == shot.n]
    return [*strings(shot.ir), shot.why, shot.sound.ambience, shot.sound.effects, shot.sound.music, *own]


def mentions(text: str, name: str) -> bool:
    """`name` appears in `text` as a whole word, ignoring case."""
    return bool(name.strip()) and re.search(rf"(?<!\w){re.escape(name.strip())}(?!\w)", text, re.IGNORECASE) is not None


def head(text: str, n: int = 6) -> str:
    return " ".join(text.split()[:n])


# ── the addition rule (also used by `jonathan_mend`, which drops what fails) ────────────────────────


def addition_fault(scene: SceneS, plan: JonathanWire, added: AddedW, removed: Sequence[tuple[str, int]] = ()) -> str:
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


def problems(scene: SceneS, plan: JonathanWire, removed: Sequence[tuple[str, int]] = ()) -> list[Problem]:
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
    # the cinematic lab's own (plan/2026-11-06 §5): a voice only heard kept out of frame, nobody speaking in a shot
    # with no
    # line, the seconds the edit keeps, the sequences and the colour script
    out += _heard_in_frame(scene, plan)
    out += _speaking(plan)
    out += _use(scene, plan)
    out += _sequences(plan)
    out += _holding(scene, plan)
    return unique(out)


def unique(found: list[Problem]) -> list[Problem]:
    """Each problem once, in order: one problem found by two checks (a heard voice in frame) is one problem."""
    out: dict[str, Problem] = {}
    for p in found:
        out.setdefault(p.id, p)
    return list(out.values())


def _shape(plan: JonathanWire) -> list[Problem]:
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


def _blocks_and_lines(scene: SceneS, plan: JonathanWire) -> list[Problem]:
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


def _clock(scene: SceneS, plan: JonathanWire) -> list[Problem]:
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


def _added(scene: SceneS, plan: JonathanWire, removed: Sequence[tuple[str, int]]) -> list[Problem]:
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


def _names(scene: SceneS, plan: JonathanWire) -> list[Problem]:
    out = []
    cast = {norm(c) for c in scene.cast}
    strangers = [n for n in scene.others if norm(n) not in cast]
    texts = {s.n: free_text(s, plan) for s in plan.shots}
    texts[0] = plan.treatment_text()
    for n, parts in texts.items():
        blob = " \n ".join(parts)
        for name in strangers:
            if mentions(blob, name):
                where = "The treatment names" if n == 0 else f"{code(n)} names"
                out.append(Problem(code="names", sentence=f"{where} {name}, who is not in this scene.",
                                   shots=[n] if n else [], key=f"names:{n}:{norm(name)}"))
    return out


def _speech(scene: SceneS, plan: JonathanWire) -> list[Problem]:
    out = []
    for s in plan.shots:
        if any(speech_in(t, scene.lines) for t in free_text(s, plan)):
            out.append(Problem(code="speech", sentence=f"{code(s.n)} has quoted speech or a line's words in its "
                               "free text; they are removed (a line reaches the prompt only as the script's).",
                               shots=[s.n], fix="mend", key=f"speech:{s.n}"))
    return out


def stage_map(scene: SceneS, plan: JonathanWire) -> stagemap.SceneStaging:
    """The author's staging as a validated map: an entry that is not true to this scene is dropped."""
    raw = {"zones": plan.staging.zones, "marks": [m.model_dump() for m in plan.staging.marks]}
    return stagemap.validate(raw, scene.items(), scene.cast, version=1, by="model")


def _staging(scene: SceneS, plan: JonathanWire) -> list[Problem]:
    staging = stage_map(scene, plan)
    if not staging.marks:
        return [Problem(code="staging", sentence="The staging map has fewer than two spots or no marks, so teleports, "
                        "crossed lines and eyelines cannot be checked.", fix="report", key="staging:none")]
    proposals: list[tuple[int, ProposedShot]] = []
    for s in plan.shots:
        known = sorted(set(s.blocks) & {b.index for b in scene.blocks})
        if known:
            proposals.append((s.n, ProposedShot(known[0], known[-1] + 1, s.framing, "", None, s.take_s, True,
                                                s.link)))
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


def _heard(scene: SceneS, plan: JonathanWire) -> list[Problem]:
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
    # a mirror, or a person's reflection in glass; not the water on a wet road (the lab's rain scene tripped the word)
    ("a mirror", r"\b(mirrors?|(?:her|his|their|a person's|own) reflection|"
     r"reflection (?:of (?:her|him|them)|in (?:a|the) (?:glass|window|mirror)))\b",
     "Veo breaks reflections: shoot the person, not the glass."),
    ("fast hands", r"\b(typing|texting|rapid(?:ly)?|dialling|dialing|shuffl\w+|juggl\w+|knitting|sewing)\b",
     "fast finger work blurs: hold on the face, or show the hands still on the object."),
    ("touching", r"\b(hug\w*|embrac\w+|kiss\w*|holds? hands|holding hands)\b", "bodies in contact merge: keep a "
     "hand's width apart, or cut away at the moment of contact."),
    ("a crowd", r"\b(crowd|dozens|hundreds|packed with people|mob)\b", "Veo invents the crowd's faces: frame a few "
     "people near, the rest soft and far."),
)


def _feasibility(plan: JonathanWire) -> list[Problem]:
    out = []
    for s in plan.shots:
        blob = " \n ".join(free_text(s, plan))
        for name, pattern, fix in FEASIBILITY:
            if re.search(pattern, blob, re.IGNORECASE):
                out.append(Problem(code="feasibility", sentence=f"{code(s.n)} asks for {name}. {fix}", shots=[s.n],
                                   fix="report", key=f"feasibility:{s.n}:{name}"))
    return out


def _end_state(scene: SceneS, plan: JonathanWire) -> list[Problem]:
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


def faults(found: list[Problem]) -> list[Problem]:
    """What makes a plan wrong: everything but a report (a keyword advisory such as a mirror is only shown)."""
    return [p for p in found if p.fix != "report"]


# ── the cinematic lab's hard checks (plan/2026-11-06 §5) ──────────────────────────────────────────────

# Someone SPEAKS: said in an action field, where only a line may be spoken. Not "answers" (answering a phone is an act).
SPEAKS = re.compile(r"\b(speaks?|speaking|says?|saying|asks?|replies|replying|shouts?|whispers?|talks?|tells?|murmurs?|"
                    r"calls? out)\b", re.IGNORECASE)


def action_text(shot: ShotW) -> list[str]:
    """What a shot says its people DO (beat actions and subject actions): speech has no place there."""
    ir = shot.ir
    beats = [str(b.get("action") or "") for b in ir.get("beats") or [] if isinstance(b, dict)]
    subjects = [str(s.get("action") or "") for s in ir.get("subjects") or [] if isinstance(s, dict)]
    return [*beats, *subjects]


def _speaking(plan: JonathanWire) -> list[Problem]:
    out = []
    for s in plan.shots:
        if s.lines:
            continue
        said = next((m.group(0) for t in action_text(s) if (m := SPEAKS.search(t))), "")
        if said:
            out.append(Problem(code="speaks", sentence=f"{code(s.n)} has no line, but a beat says someone \"{said}\": "
                               "nobody speaks in a shot with no line (Veo invents the speech). Say what they DO.",
                               shots=[s.n], key=f"speaks:{s.n}"))
    return out


def _use(scene: SceneS, plan: JonathanWire) -> list[Problem]:
    out = []
    for s in plan.shots:
        if not 2 <= s.use_s <= s.take_s:
            out.append(Problem(code="use", sentence=f"{code(s.n)} keeps {s.use_s} s of a {s.take_s} s take: `use_s` is "
                               "2 to the take.", shots=[s.n], key=f"use:range:{s.n}"))
        lines = [i for i in items_of(scene, s) if i.is_line]
        need = need_s(lines) if lines else 0.0
        if lines and s.use_s + 1e-9 < need:
            out.append(Problem(code="use", sentence=f"{code(s.n)} keeps {s.use_s} s, but its line needs "
                               f"{need:.1f} s: a line is kept whole.", shots=[s.n], key=f"use:line:{s.n}"))
    return out


def _sequences(plan: JonathanWire) -> list[Problem]:
    if not plan.sequences:
        return [Problem(code="sequence", sentence="The plan has no sequences.", key="sequence:none")]
    out = []
    ids = [q.id for q in plan.sequences]
    if len(set(ids)) != len(ids):
        out.append(Problem(code="sequence", sentence="Two sequences have the same id.", key="sequence:duplicate"))
    for s in plan.shots:
        if s.sequence not in ids:
            out.append(Problem(code="sequence", sentence=f"{code(s.n)} is in sequence \"{s.sequence}\", which does not "
                               "exist.", shots=[s.n], key=f"sequence:unknown:{s.n}"))
    for q in plan.sequences:
        mine = [s.n for s in plan.shots if s.sequence == q.id]
        if not mine:
            out.append(Problem(code="sequence", sentence=f"Sequence {q.id} has no shot.", key=f"sequence:empty:{q.id}"))
        elif mine != list(range(mine[0], mine[-1] + 1)):
            out.append(Problem(code="sequence", sentence=f"Sequence {q.id}'s shots are not one run.", shots=mine,
                               key=f"sequence:run:{q.id}"))
        elif (q.shots.first, q.shots.last) != (mine[0], mine[-1]):
            out.append(Problem(code="sequence", sentence=f"Sequence {q.id} says shots {q.shots.first}-{q.shots.last}, "
                               f"but its shots are {mine[0]}-{mine[-1]}.", shots=mine, fix="mend",
                               key=f"sequence:span:{q.id}"))
    named = {c.sequence for c in plan.treatment.colour_script}
    for q in plan.sequences:
        if q.id not in named:
            out.append(Problem(code="colour", sentence=f"The colour script does not name sequence {q.id}.",
                               key=f"colour:{q.id}"))
    for extra in sorted(named - set(ids)):
        out.append(Problem(code="colour", sentence=f"The colour script names sequence \"{extra}\", which does not "
                           "exist.",
                           key=f"colour:unknown:{extra}"))
    if not plan.treatment.arc:
        out.append(Problem(code="sequence", sentence="The treatment has no arc.", key="treatment:arc"))
    return out


def _heard_in_frame(scene: SceneS, plan: JonathanWire) -> list[Problem]:
    """A voice that is only heard (judged by its lines, `heard_names`) is in no subject and no first frame."""
    out = []
    for who in heard_names(scene):
        for s in plan.shots:
            seen = [*strings(s.ir.get("subjects")), *strings(s.ir.get("first_frame"))]
            if any(mentions(t, who) for t in seen):
                out.append(Problem(code="heard", sentence=f"{who} is only heard (a voice on the phone) and is in "
                                   f"{code(s.n)}'s subjects or first frame: take them out of the picture.", shots=[s.n],
                                   key=f"heard:{s.n}:{norm(who)}"))
    return out


# ── who holds what: every change of hands the script writes is in the staging (the frames are painted from it) ──────

# What the script does with a thing, and the thing is the words after the verb, up to a preposition
TAKE = re.compile(r"\b(picks? up|picked up|picks?(?= (?:it|them) up)|picked(?= (?:it|them) up)|"
                  r"grabs?|grabbed|takes?|took|lifts?|holds?|holding|carries|carrying|"
                  r"catch(?:es)?|caught|receives?|accepts?)\s+(?P<thing>[^.,;!?]+)", re.IGNORECASE)
DROP = re.compile(r"\b(drops?|dropped|puts? down|sets? down|lets? go of|let go of|throws?|threw|tosses?|tossed|"
                  r"puts? away|pockets?)\s+(?P<thing>[^.,;!?]+)", re.IGNORECASE)
GIVE = re.compile(r"\b(gives?|gave|hands?|handed|returns?|returned|passes?|passed)\s+(?:(?:it|her|him|them)\s+)?"
                  r"(?:back\s+|over\s+)?(?P<thing>[^.,;!?]+)", re.IGNORECASE)
_UNTIL = re.compile(r"\s(?:near|by|to|from|at|on|in|into|onto|under|over|off|with|after|before|behind|towards?|back|up|"
                    r"down|and|as|while|then)\b.*$", re.IGNORECASE)
# What a verb above can take that is not a thing in a hand
NOT_THINGS = frozenset({"breath", "step", "steps", "look", "glance", "gaze", "moment", "seat", "chin", "hand", "hands",
                        "head", "pause", "time", "turn", "smile", "sip", "bite", "note", "notice", "chance", "place",
                        "care", "stock", "aim", "shape", "hold", "courage", "eyes", "eye", "face", "breaths", "it",
                        "her", "him", "them", "this", "that", "deep", "seconds", "second", "minute", "call", "lead",
                        "part", "control", "charge", "position", "stand", "attention"})


PRONOUNS = frozenset({"it", "them"})


def _thing(text: str, last: str = "") -> str:
    """The thing a verb acts on; "it" is the last thing an earlier action named ("Kasun picks it up")."""
    words = text.strip().split()
    if words and words[0].lower().strip(".,;") in PRONOUNS:
        return last
    t = thing_of(_UNTIL.sub("", text.strip()))
    return t.key if t is not None and t.key not in NOT_THINGS and not t.worn else ""


def _holding(scene: SceneS, plan: JonathanWire) -> list[Problem]:
    """The frames are painted from the staging's `holding` (`contracts.holding`), one holder per thing. So each action
    that puts a thing in a hand, takes it out, or passes it on must show in the marks at that block: otherwise the
    painter is never told, and the phone is at the ear of the woman who just dropped it. Who did it is not guessed
    (a pronoun); only whether the thing changes hands where the script says."""
    ledger = Ledger.of(m.model_dump() for m in plan.staging.marks)
    out: list[Problem] = []
    last = ""  # the thing the last action named, for "it"
    for b in sorted(scene.blocks, key=lambda x: x.index):
        if b.kind != "action":
            continue
        before, after = ledger.at(b.index), ledger.at(b.index + 1)
        named = ""
        for pattern, kind in ((DROP, "drop"), (GIVE, "give"), (TAKE, "take")):
            for m in pattern.finditer(b.text):
                key = _thing(m.group("thing"), last)
                if not key:
                    continue
                named = named or key
                said = f"b{b.index} (\"{head(b.text, 8)}\")"
                was, now = before.get(key, ("", None))[0], after.get(key, ("", None))[0]
                if kind == "drop" and not was:
                    out.append(Problem(code="holding", key=f"holding:before:{b.index}:{key}", sentence=(
                        f"{said} has the {key} let go of, but no mark has anyone holding the {key} before b{b.index}: "
                        "give its holder a mark from the scene's start (or where they get it) with `holding` naming "
                        "it.")))
                elif kind == "drop" and now:
                    out.append(Problem(code="holding", key=f"holding:after:{b.index}:{key}", sentence=(
                        f"{said} has the {key} let go of, but {now} still holds it after b{b.index}: give {now} a "
                        f"mark at b{b.index} whose `holding` leaves it out.")))
                elif kind == "give" and (not now or now == was):
                    out.append(Problem(code="holding", key=f"holding:give:{b.index}:{key}", sentence=(
                        f"{said} passes the {key} on, but the marks do not move it to its new holder at b{b.index}: "
                        "give the one who receives it a mark there with `holding` naming it.")))
                elif kind == "take" and not now:
                    out.append(Problem(code="holding", key=f"holding:take:{b.index}:{key}", sentence=(
                        f"{said} puts the {key} in someone's hands, but no mark has anyone holding it from "
                        f"b{b.index}: give the holder a mark at b{b.index} with `holding` naming it.")))
                break  # one finding per verb kind and block
        last = named or last
    return unique(out)
