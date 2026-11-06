"""Code fixes what code can (plan/2026-11-05e §4.3 `david_mend`, §6): a take that is too short, a crowded shot,
speech in
free text, an addition the checks refuse, the numbering.

    mend(scene, plan, removed=…)   → (the plan, what was mended in sentences, the additions it dropped as problems)

A mend is never a deletion of the script and never a trimmed line: a shot is made longer, or cut at a block boundary
(a line stays whole in one part); what code cannot mend stays for the checks to report or for a repair.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from contracts.david.checks import addition_fault, code, free_text
from contracts.david.plan import Problem
from contracts.david.scene import SceneS, items_of, need_s, shortest_take, speech_in, split_items, strip_speech
from contracts.david.wire import DavidWire
from contracts.veo import VEO_DURATIONS


def _scrub(value: Any, scene: SceneS) -> Any:
    if isinstance(value, str):
        return strip_speech(value, scene.lines)
    if isinstance(value, dict):
        return {k: _scrub(v, scene) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v, scene) for v in value]
    return value


def mend(scene: SceneS, plan: DavidWire, removed: Sequence[tuple[str, int]] = ()
         ) -> tuple[DavidWire, list[str], list[Problem]]:
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
    # ② quoted speech and Sinhala in free text
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
    # ③ the clock: a longer take, else a cut at a block boundary
    longest = max(VEO_DURATIONS)
    shots, added, first_of = [], list(plan.added), {}
    for s in plan.shots:
        items = items_of(scene, s)
        need = need_s(items)
        first_of[s.n] = len(shots) + 1
        if need <= s.take_s + 1e-9:
            shots.append(s)
            continue
        take = shortest_take(need)
        if take:
            done.append(f"{code(s.n)}: a {take} s take, not {s.take_s} s (it needs {need:.1f} s)")
            shots.append(s.model_copy(update={"take_s": take}))
            continue
        parts = split_items(items, longest)
        if len(parts) < 2:
            shots.append(s)  # one line or action longer than the longest take: reported, never trimmed
            continue
        for k, group in enumerate(parts):
            lines = [i.line_id for i in group if i.is_line and i.line_id]
            take = shortest_take(need_s(group)) or longest
            shots.append(s.model_copy(update={
                "blocks": [i.index for i in group], "lines": lines, "over": s.over if lines else "", "take_s": take,
                "link": s.link if k == 0 else ("continuous" if group[0].is_line else "cut"),
                "why": s.why if k == 0 else f"{s.why} (continued)"}))
        done.append(f"{code(s.n)}: split into {len(parts)} shots at a block boundary (it needed "
                    f"{need:.1f} s; the longest take is {longest} s); the parts keep its camera design")
    plan = plan.model_copy(update={
        "shots": [s.model_copy(update={"n": i}) for i, s in enumerate(shots, start=1)],
        "added": [a.model_copy(update={"shot": first_of.get(a.shot, a.shot)}) for a in added]})
    return plan, done, dropped

