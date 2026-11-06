"""Code fixes what code can (plan/2026-11-06b §4.1, from the cinematic lab's `mend.py`): an addition the checks refuse,
speech in free text, a take that is too short, a crowded shot, the seconds the edit keeps of a line, the numbering, the
sequences' spans and the end state's place names.

    mend(scene, plan, removed=…)   → (the plan, what was mended in sentences, the additions it dropped as problems)

A mend is never a deletion of the script and never a trimmed line: a shot is made longer, or cut at a block boundary (a
line stays whole in one part); what code cannot mend stays for the checks to report or for the reviser.

The SPLIT FIX (the lab's finding F8): when a shot is cut in two, each part keeps only the beats that fall inside its own
blocks, re-timed from 0 (David's mend copies the whole design into both halves, so the part with no line still "speaks"
and an action plays twice); a part with no line is told to be silent, and its `use_s` follows its own need.
"""
from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Any

from contracts import stagemap
from contracts.jonathan.checks import addition_fault, code, free_text, stage_map
from contracts.jonathan.plan import Problem, norm
from contracts.jonathan.scene import SceneS, items_of, need_s, shortest_take, speech_in, split_items, strip_speech
from contracts.jonathan.wire import JonathanWire, ShotW
from contracts.shotplan import Item
from contracts.veo import VEO_DURATIONS

WINDOW = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*s?\s*$")


def _scrub(value: Any, scene: SceneS) -> Any:
    if isinstance(value, str):
        return strip_speech(value, scene.lines)
    if isinstance(value, dict):
        return {k: _scrub(v, scene) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v, scene) for v in value]
    return value


def _window(beat: dict[str, Any]) -> tuple[float, float] | None:
    m = WINDOW.match(str(beat.get("time") or ""))
    return (float(m.group(1)), float(m.group(2))) if m else None


def _stamp(a: float, b: float) -> str:
    return f"{a:g}-{b:g}s"


def part_beats(beats: list[Any], start: float, end: float, take: int, *, last: bool = False) -> list[dict[str, Any]]:
    """The beats that belong to the window [start, end) of the shot they came from: each beat goes to the part that
    holds
    its midpoint (a beat is never copied into two parts), and the part's beats are re-timed from 0 to tile its take,
    each
    in proportion to the time it had. A window no beat's midpoint falls in gets the nearest beat, so a part is never
    left
    without one."""
    timed = [(w, b) for b in beats if isinstance(b, dict) and (w := _window(b)) is not None]
    if not timed:
        return [dict(b) for b in beats if isinstance(b, dict)][:1]
    mine = [(w, b) for w, b in timed if start <= (w[0] + w[1]) / 2 < end or (last and (w[0] + w[1]) / 2 >= end)]
    if not mine:
        middle = (start + end) / 2
        mine = [min(timed, key=lambda wb: abs((wb[0][0] + wb[0][1]) / 2 - middle))]
    total = sum(max(w[1] - w[0], 0.5) for w, _ in mine)
    out, cursor = [], 0.0
    for k, (w, b) in enumerate(mine):
        span = take * max(w[1] - w[0], 0.5) / total
        stop = float(take) if k == len(mine) - 1 else cursor + span
        out.append({**b, "time": _stamp(cursor, stop)})
        cursor = stop
    return out


def _part_use(group: list[Item], take: int) -> int:
    return min(take, max(2, math.ceil(need_s(group) - 1e-9)))


def split(shot: ShotW, parts: list[list[Item]]) -> list[ShotW]:
    """One shot cut at block boundaries into its parts, each with only its own beats (the fix of finding F8)."""
    needs = [max(need_s(g), 0.5) for g in parts]
    original = max(
        (w[1] for b in shot.ir.get("beats") or [] if isinstance(b, dict) and (w := _window(b)) is not None),
        default=float(shot.take_s))
    longest = max(VEO_DURATIONS)
    out = []
    cursor = 0.0
    for k, group in enumerate(parts):
        span = original * needs[k] / sum(needs)
        start, end = cursor, cursor + span
        cursor = end
        lines = [i.line_id for i in group if i.is_line and i.line_id]
        take = shortest_take(need_s(group)) or longest
        ir = {**shot.ir, "beats": part_beats(list(shot.ir.get("beats") or []), start, end, take,
                                             last=k == len(parts) - 1)}
        sound = shot.sound if lines else shot.sound.model_copy(update={"silence": True})
        out.append(shot.model_copy(update={
            "blocks": [i.index for i in group], "lines": lines, "over": shot.over if lines else "", "take_s": take,
            "use_s": _part_use(group, take), "ir": ir, "sound": sound,
            "link": shot.link if k == 0 else ("continuous" if group[0].is_line else "cut"),
            "why": shot.why if k == 0 else f"{shot.why} (continued)"}))
    return out


def _end_places(scene: SceneS, plan: JonathanWire) -> tuple[JonathanWire, list[str]]:
    """The end state's place for each person, written as the staging's last mark names it when the two disagree only in
    words ("off screen phone" for the zone "off screen, on the phone"): code can read the staging, so it is not the
    author's to fix. A person the staging never marks keeps the author's words."""
    staging = stage_map(scene, plan)
    if not staging.marks:
        return plan, []
    last = max((b.index for b in scene.blocks), default=0)
    people, done = [], []
    for p in plan.end_state.people:
        mark = staging.mark_at(scene.items(), p.who, last)
        if mark is not None and mark.zone != stagemap.OFF:
            here, zone = norm(p.where), norm(mark.zone)
            if zone not in here and here not in zone:
                done.append(f"the end state: {p.who} is at \"{mark.zone}\", as the staging ends them "
                            f"(not \"{p.where}\")")
                p = p.model_copy(update={"where": mark.zone})
        people.append(p)
    if not done:
        return plan, []
    return plan.model_copy(update={"end_state": plan.end_state.model_copy(update={"people": people})}), done


def mend(scene: SceneS, plan: JonathanWire, removed: Sequence[tuple[str, int]] = ()
         ) -> tuple[JonathanWire, list[str], list[Problem]]:
    done: list[str] = []
    dropped: list[Problem] = []
    plan = plan.renumbered()  # first: every later step names a shot by its number
    # ① additions code refuses: the record goes, and a shot that exists only for it goes with it
    bad = {i: why for i, a in enumerate(plan.added) if (why := addition_fault(scene, plan, a, removed))}
    if bad:
        gone: set[int] = set()
        for i, why in bad.items():
            a = plan.added[i]
            shot = plan.shot(a.shot)
            dropped.append(Problem(code="added", sentence=why + " It is dropped.", shots=[a.shot] if shot else [],
                                   fix="drop", key=f"added:{a.shot}:{a.kind}"))
            if shot is not None and not shot.blocks and not shot.lines:
                gone.add(shot.n)
        kept = [a for i, a in enumerate(plan.added) if i not in bad]
        plan = plan.model_copy(update={"added": kept}).without(gone)
    # ② quoted speech and Sinhala in free text, the treatment's included
    shots = []
    for s in plan.shots:
        if any(speech_in(t, scene.lines) for t in free_text(s, plan)):
            s = s.model_copy(update={"ir": _scrub(s.ir, scene), "why": strip_speech(s.why, scene.lines),
                                     "sound": s.sound.model_copy(update={
                                         k: strip_speech(getattr(s.sound, k), scene.lines)
                                         for k in ("ambience", "effects", "music")})})
            done.append(f"{code(s.n)}: speech removed from its free text")
        shots.append(s)
    plan = plan.model_copy(update={"shots": shots})
    if any(speech_in(t, scene.lines) for t in plan.treatment_text()):
        data = plan.model_dump()
        data["treatment"], data["sequences"] = _scrub(data["treatment"], scene), _scrub(data["sequences"], scene)
        plan = JonathanWire.model_validate(data)
        done.append("the treatment: speech removed")
    # ③ the clock: a longer take, else a cut at a block boundary (each part with its own beats)
    longest = max(VEO_DURATIONS)
    out: list[ShotW] = []
    first_of: dict[int, int] = {}
    for s in plan.shots:
        items = items_of(scene, s)
        need = need_s(items)
        first_of[s.n] = len(out) + 1
        if need <= s.take_s + 1e-9:
            out.append(s)
            continue
        take = shortest_take(need)
        if take:
            done.append(f"{code(s.n)}: a {take} s take, not {s.take_s} s (it needs {need:.1f} s)")
            out.append(s.model_copy(update={"take_s": take}))
            continue
        parts = split_items(items, longest)
        if len(parts) < 2:
            out.append(s)  # one line or action longer than the longest take: reported, never trimmed
            continue
        out += split(s, parts)
        done.append(f"{code(s.n)}: split into {len(parts)} shots at a block boundary (it needed {need:.1f} s; the "
                    f"longest take is {longest} s); each part keeps only its own beats, re-timed from 0")
    # ④ a line is kept whole: the edit never keeps less than a line needs, and never more than the take
    final = []
    for s in out:
        lines = [i for i in items_of(scene, s) if i.is_line]
        use = max(s.use_s, math.ceil(need_s(lines) - 1e-9)) if lines else s.use_s
        use = min(use, s.take_s)
        if use != s.use_s and use >= 2:
            done.append(f"{code(s.n)}: keeps {use} s, not {s.use_s} s (a line is kept whole)")
            s = s.model_copy(update={"use_s": use})
        final.append(s)
    plan = plan.model_copy(update={
        "shots": [s.model_copy(update={"n": i}) for i, s in enumerate(final, start=1)],
        "added": [a.model_copy(update={"shot": first_of.get(a.shot, a.shot)}) for a in plan.added]}).respanned()
    # ⑤ the end state's places, as the staging ends them
    plan, places = _end_places(scene, plan)
    return plan, done + places, dropped
