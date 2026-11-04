"""The producer's own bookkeeping, ported from `shot_producer/engine/pipeline.py` (plan/2026-11-03 Phase 6): the text
that names a scene for the craft-problem question, the design row a shot stores, and a new prompt version's row,
serialized in code from the stored design. No model, no store.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from contracts.producer import CameraSettings, prompt_text
from contracts.staging import AUTHORED
from hiru_ai.core import parts
from hiru_ai.steps.serialize import logic as serialize
from hiru_ai.steps.serialize import shots
from hiru_ai.steps.serialize.model import ProductionInput, SceneInput, ShotInput

Row = dict[str, Any]
VIDEO_MODEL = "Veo 3.1"
positions_text = parts.step("feeling").positions_text


def now() -> str:
    return datetime.now(UTC).isoformat()


def scene_text(scene: SceneInput) -> str:
    """A scene in a few lines, for the question "what is hard to film here?"."""
    actions = [i.text.strip() for s in scene.shots for i in s.items if i.kind == "action" and i.text.strip()]
    heard = sorted({c.name for s in scene.shots for c in s.heard})
    return (f"SCENE {scene.number}: {scene.title or scene.heading}\n" + " / ".join(actions[:8])
            + (f"\nHeard but not seen: {', '.join(heard)}" if heard else ""))


def drop_agent_intent(shot: ShotInput) -> None:
    """An intent about to be rewritten must not steer who the rules think is seen."""
    row_intent = shot.row.get("intent") or {}
    if row_intent and row_intent.get("by") not in AUTHORED:
        shot.row = {**shot.row, "intent": {}}


def design_row(shot: ShotInput, ir: Row, rec: CameraSettings, why: str, planner: str, on_screen: list[str],
               job_id: str) -> Row:
    it = shot.intent
    return {"recommended": rec.model_dump(), "rationale": why, "planner": planner,
            "pins": shot.pins.model_dump(), "designed_at": now(), "job_id": job_id,
            "missing": shots.get_schema().missing_keys(ir), "on_screen": on_screen,
            "intent": it.stamp() if it is not None else ""}


def write_prompt(shot: ShotInput, scene: SceneInput, prod: ProductionInput, frame: Row | None, job_id: str,
                 actor: str) -> Row:
    """A new prompt version's row, serialized in code from the stored IR."""
    carried_state = parts.step("serialize", "continuity").carried_state
    previous = next((s for s in scene.shots if s.number == shot.number - 1), None)
    ctx = serialize.Context(aspect_ratio=prod.aspect_ratio, camera=shot.camera(scene),
                            recommended=shot.recommended(scene), style_note=prod.style_note,
                            previous_code=previous.code if previous else "",
                            carried=carried_state(previous.code, previous.row.get("ir"),
                                                  positions_text(previous.feeling.end)) if previous else "",
                            has_frame=frame is not None)
    ir = dict(shot.row.get("ir") or {})
    sections = serialize.build_sections(shot, ir, ctx)
    return {"production_id": prod.id, "shot_id": shot.id,
            "sections": [s.model_dump(exclude_none=True) for s in sections], "prose": prompt_text(sections),
            "model": f"{VIDEO_MODEL} · {shot.duration_s} s · {prod.aspect_ratio}", "ir": ir,
            "camera": ctx.camera.model_dump(),
            "checks": [c.model_dump() for c in serialize.prompt_checks(shot, sections, ctx, ir)],
            "frame_id": str(frame["id"]) if frame else None, "pins": shot.pins.model_dump(), "job_id": job_id,
            "created_by": actor}
