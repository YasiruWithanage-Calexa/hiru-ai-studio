"""A second look at a scene's camera design, before any frame is painted (plan/2026-11-01 §C).

Ported from PromptMotion Nova's producer (`_critique` → one revision → keep it only if it still
passes the free checks). Bounded on purpose: ONE review, at most ONE revision, and the revision of
a shot is kept only when the free checks find no more problems in it than in the first draft. An
open-ended "make it better" loop drifts away from the script and costs without a ceiling.

Two layers, cheap first:
* `free_problems`: the staging checks (contracts.staging) on a draft, in code, for nothing;
* `review`: the model reads the drafts against the intent and the free problems and names at
  most four concrete problems. No notes → the first draft stands.

Absent-safe: no key, or a failed call → no notes, the first draft stands.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from contracts.producer import FRAMING_LABEL, CameraSettings
from contracts.staging import ShotIntent, coverage_checks, staging, staging_checks
from hiru_ai.core import parts
from hiru_ai.steps.serialize.intent import context_block
from hiru_ai.steps.serialize.model import SceneInput, ShotInput

_logger = logging.getLogger(__name__)
_feeling = parts.step("feeling")
performance_missing, position_jump = _feeling.performance_missing, _feeling.position_jump
Row = dict[str, Any]
MAX_NOTES = 4


def free_problems(shot: ShotInput, ir: Mapping[str, Any], on_screen: list[str], characters: list[Row],
                  scene: SceneInput | None = None) -> list[str]:
    """The staging advisories a draft would get, as labels (the panel's checks, run on a draft), and (plan/2026-11-01d)
    `performance_missing` (a beat where the feeling turns has none written) and `position_jump` (the first frame is
    set where the people did not stand)."""
    row = {**shot.row, "ir": dict(ir), "design": {**(shot.row.get("design") or {}), "on_screen": on_screen}}
    staged = staging(shot.items, characters, row, cast_ids=[c.id for c in shot.cast])
    checks = staging_checks(staged=staged, names={c.id: c.name for c in shot.cast}, sound_mode=shot.sound_mode,
                            speaker_ids=shot.speaker_ids, ir=ir, design_on_screen=on_screen,
                            intent=ShotIntent.of(row), items=shot.items, framing=shot.framing)
    out = [c.label for c in checks if c.tone != "pass"]
    beats = [b for b in ir.get("beats") or [] if isinstance(b, Mapping)]
    missing = performance_missing(shot.feeling, beats, shot.beats)
    if missing:
        out.append(f"No performance in the beat at {', '.join(missing)}, where the feeling turns")
    if scene is not None and scene.staging is not None:
        previous = next((s for s in scene.shots if s.number == shot.number - 1), None)
        names = {p.who.casefold() for p in shot.feeling.start}
        carried = [p for p in (previous.feeling.end if previous else []) if p.who.casefold() in names]
        jump = position_jump(scene.staging.zones, carried or shot.feeling.start, ir)
        if jump:
            out.append(f"Position jump: {jump}")
    return out


def scene_coverage_problems(scene: SceneInput, cameras: dict[int, CameraSettings]) -> list[str]:
    shots = [s for s in scene.shots if s.number in cameras]
    per_shot = coverage_checks([s.framing for s in shots], [cameras[s.number] for s in shots],
                               [s.code for s in shots])
    return [f"{s.code}: {c.label}" for s, checks in zip(shots, per_shot, strict=True) for c in checks]


def _draft(shot: ShotInput, ir: Mapping[str, Any], on_screen: list[str]) -> str:
    cine = ir.get("cinematography") if isinstance(ir.get("cinematography"), Mapping) else {}
    frame = ir.get("first_frame") if isinstance(ir.get("first_frame"), Mapping) else {}
    intent = shot.intent
    seen = ", ".join(c.name for c in shot.cast if c.id in on_screen) or "nobody identified"
    heard = ", ".join(c.name for c in shot.heard)
    beats = [b for b in ir.get("beats") or [] if isinstance(b, Mapping)]
    lines = [f"{shot.code} — {FRAMING_LABEL.get(shot.framing, shot.framing)}, {shot.duration_s} s, sound "
             f"{shot.sound_mode}",
             f"  PURPOSE: {intent.purpose}" if intent and intent.purpose else "",
             f"  WHAT WE SEE: {intent.what_we_see}" if intent and intent.what_we_see else "",
             f"  SCRIPT ACTIONS: {' / '.join(i.text.strip() for i in shot.items if i.kind == 'action' and i.text)}",
             f"  ON SCREEN: {seen}" + (f" · HEARD ONLY: {heard}" if heard else ""),
             f"  CAMERA: {(cine or {}).get('camera', '')}; {(cine or {}).get('angle', '')}; "
             f"{(cine or {}).get('movement', '')}",
             f"  FIRST FRAME: {(frame or {}).get('composition', '')} | "
             + "; ".join(str(x) for x in (frame or {}).get("subjects") or []),
             "  BEATS: " + " / ".join(f"{b.get('time', '')} {b.get('action', '')}"
                                  + (f" [performance: {b['performance']}]" if b.get("performance") else "")
                                  for b in beats)]
    return "\n".join(x for x in lines if x)


def review_input(scene: SceneInput, drafts: list[tuple[ShotInput, Row, list[str]]], free: list[str]) -> Row:
    """What the `shot_critic` agent reads: the scene, its context and coverage plan, each draft, and what code found."""
    return {"scene_number": scene.number, "heading": scene.heading, "context": context_block(scene),
            "plan": scene.plan.text() if scene.plan and scene.plan.text() else "",
            "drafts": [_draft(s, ir, on) for s, ir, on in drafts], "free": free}


def review(ask: Callable[[Row], list[str]] | None, scene: SceneInput,
           drafts: list[tuple[ShotInput, Row, list[str]]], free: list[str]) -> list[str]:
    """-> at most MAX_NOTES notes; [] = keep the first draft. `ask(input)` is the `shot_critic` agent's notes (it caps
    them and says none when the model is content and code found nothing); no model or a failed call has none."""
    if ask is None or not drafts:
        return []
    try:
        return list(ask(review_input(scene, drafts, free)))
    except Exception:
        _logger.warning("scene %s design review failed", scene.id, exc_info=True)
        return []
