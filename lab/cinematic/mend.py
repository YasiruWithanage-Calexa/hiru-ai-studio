"""What code mends in a cinematic plan (plan/2026-11-06 §4.6): the same four steps as `contracts.david.mend`, on a
`CinemaWire`, with the split fixed (finding F8).

`contracts.david.mend.mend` is one function over a `DavidWire`, so the lab cannot use it and keep its own fields; this
module uses the same building blocks (`addition_fault`, `free_text`, `strip_speech`, the clock) in the same order:

    ① additions the checks refuse are dropped (a shot that exists only for one goes too)
    ② quoted speech and Sinhala are scrubbed from free text (the treatment included)
    ③ the clock: a longer take, else a cut at a block boundary

The split fix: when a shot is cut in two, each part keeps only the beats that fall inside its own blocks, re-timed from
0 (the contracts' mend copies the whole design into both halves: the part with no line then still "speaks", and the tea
is drunk twice); a part with no line is told to be silent, and `use_s` follows the part's own need. A line still never
leaves its block and is never trimmed.
"""
from __future__ import annotations

import math
import re
from typing import Any

from contracts.david.checks import addition_fault, code, free_text
from contracts.david.plan import Problem
from contracts.david.scene import SceneS, items_of, need_s, shortest_take, speech_in, split_items, strip_speech
from contracts.shotplan import Item
from contracts.veo import VEO_DURATIONS

from .schema import CinemaShotW, CinemaWire, SequenceW, SpanW

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
    """The beats that belong to the window [start, end) of the shot they came from: each beat goes to the part that holds
    its midpoint (a beat is never copied into two parts), and the part's beats are re-timed from 0 to tile its take, each
    in proportion to the time it had. A window no beat's midpoint falls in gets the nearest beat, so a part is never left
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


def split(scene: SceneS, shot: CinemaShotW, parts: list[list[Item]]) -> list[CinemaShotW]:
    """One shot cut at block boundaries into its parts (the fix of finding F8)."""
    needs = [max(need_s(g), 0.5) for g in parts]
    original = max(
        (w[1] for b in shot.ir.get("beats") or [] if isinstance(b, dict) and (w := _window(b)) is not None),
        default=float(shot.take_s))
    out = []
    cursor = 0.0
    for k, group in enumerate(parts):
        span = original * needs[k] / sum(needs)
        start, end = cursor, cursor + span
        cursor = end
        lines = [i.line_id for i in group if i.is_line and i.line_id]
        take = shortest_take(need_s(group)) or max(VEO_DURATIONS)
        ir = {**shot.ir, "beats": part_beats(list(shot.ir.get("beats") or []), start, end, take,
                                             last=k == len(parts) - 1)}
        sound = shot.sound if lines else shot.sound.model_copy(update={"silence": True})
        out.append(shot.model_copy(update={
            "blocks": [i.index for i in group], "lines": lines, "over": shot.over if lines else "", "take_s": take,
            "use_s": _part_use(group, take), "ir": ir, "sound": sound,
            "link": shot.link if k == 0 else ("continuous" if group[0].is_line else "cut"),
            "why": shot.why if k == 0 else f"{shot.why} (continued)"}))
    return out


def respan(plan: CinemaWire) -> CinemaWire:
    """The sequences' shot spans, written again from the shots' own `sequence` (shots moved when one was cut or dropped)."""
    spans: list[SequenceW] = []
    for q in plan.sequences:
        mine = [s.n for s in plan.shots if s.sequence == q.id]
        spans.append(q.model_copy(update={"shots": SpanW(first=min(mine), last=max(mine))}) if mine else q)
    return plan.model_copy(update={"sequences": spans})


def _renumber(plan: CinemaWire) -> CinemaWire:
    """The shots numbered 1.. in the order they play, the additions following; one that names a shot the list lacks goes."""
    new = {s.n: i for i, s in enumerate(plan.shots, start=1)}
    if len(new) != len(plan.shots):  # numbers repeated: keep list order, drop none
        shots = [s.model_copy(update={"n": i}) for i, s in enumerate(plan.shots, start=1)]
        return plan.model_copy(update={"shots": shots, "added": [a for a in plan.added if 1 <= a.shot <= len(shots)]})
    return plan.model_copy(update={
        "shots": [s.model_copy(update={"n": new[s.n]}) for s in plan.shots],
        "added": sorted((a.model_copy(update={"shot": new[a.shot]}) for a in plan.added if a.shot in new),
                        key=lambda a: a.shot)})


def mend(scene: SceneS, plan: CinemaWire) -> tuple[CinemaWire, list[str], list[Problem]]:
    done: list[str] = []
    dropped: list[Problem] = []
    plan = _renumber(plan)
    # ① additions the checks refuse
    bad = {i: why for i, a in enumerate(plan.added) if (why := addition_fault(scene, plan.to_david(), a))}
    if bad:
        gone: set[int] = set()
        for i, why in bad.items():
            a = plan.added[i]
            shot = plan.shot(a.shot)
            dropped.append(Problem(code="added", sentence=why + " It is dropped.", shots=[a.shot] if shot else [],
                                   fix="drop", key=f"added:{a.shot}:{a.kind}"))
            if shot is not None and not shot.blocks and not shot.lines:
                gone.add(shot.n)
        plan = plan.model_copy(update={"added": [a for i, a in enumerate(plan.added) if i not in bad]})
        plan = _renumber(plan.model_copy(update={
            "shots": [s for s in plan.shots if s.n not in gone], "added": [a for a in plan.added if a.shot not in gone]}))
    # ② quoted speech and Sinhala in free text
    david = plan.to_david()
    shots = []
    for s in plan.shots:
        if any(speech_in(t, scene.lines) for t in free_text(s.david(), david)):
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
        plan = CinemaWire.model_validate(data)
        done.append("the treatment: speech removed")
    # ③ the clock: a longer take, else a cut at a block boundary
    longest = max(VEO_DURATIONS)
    out: list[CinemaShotW] = []
    first_of: dict[int, int] = {}
    for s in plan.shots:
        items = items_of(scene, s.david())
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
        out += split(scene, s, parts)
        done.append(f"{code(s.n)}: split into {len(parts)} shots at a block boundary (it needed {need:.1f} s; the "
                    f"longest take is {longest} s); each part keeps only its own beats, re-timed from 0")
    # a line is kept whole: the edit never keeps less than a line needs, and never more than the take
    final = []
    for s in out:
        lines = [i for i in items_of(scene, s.david()) if i.is_line]
        use = max(s.use_s, math.ceil(need_s(lines) - 1e-9)) if lines else s.use_s
        use = min(use, s.take_s)
        if use != s.use_s and 2 <= use:
            done.append(f"{code(s.n)}: keeps {use} s, not {s.use_s} s (a line is kept whole)")
            s = s.model_copy(update={"use_s": use})
        final.append(s)
    plan = plan.model_copy(update={
        "shots": [s.model_copy(update={"n": i}) for i, s in enumerate(final, start=1)],
        "added": [a.model_copy(update={"shot": first_of.get(a.shot, a.shot)}) for a in plan.added]})
    return respan(plan), done, dropped
