"""One shot_producer job: design the shots that need it, and (mode `prompt`) write their prompts.

    state.mode        "design" (default) | "prompt"
    state.scene_ids   scenes to work on, or
    state.shot_ids    shots to work on (their scenes are read whole: a scene is designed as one)
    state.force       re-design shots whose design is still current
    state.*           anything else is handed on to the next hop (frame_render's `frame_ids`)

A design is redone only when it is missing, out of date (its pins moved) or forced; a person's
camera changes live in `shots.camera_overrides`, which this function never writes. A prompt is a
NEW version every time: earlier versions stay as they were.

Idempotent enough for Cloud Tasks: a re-delivery of a finished job is skipped; one cut short
re-designs nothing that is already current, and at worst adds one more prompt version.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from contracts.producer import prompt_text
from shot_producer.engine import serialize, shots, techniques
from shot_producer.engine.continuity import ContinuityLedger, carried_state
from shot_producer.engine.model import (
    ProductionInput,
    SceneInput,
    ShotInput,
    design_stale,
    production_input,
    scene_input,
)

_logger = logging.getLogger(__name__)
AGENT_DP = "director_of_photography"
AGENT_PROMPT = "prompt_writer"
VIDEO_MODEL = "Veo 3.1"
Row = dict[str, Any]


class StoreLike(Protocol):
    def production(self, production_id: UUID) -> Row | None: ...
    def scenes(self, production_id: UUID, scene_ids: list[str]) -> list[Row]: ...
    def shots(self, scene_id: str) -> list[Row]: ...
    def shot_scenes(self, production_id: UUID, shot_ids: list[str]) -> list[str]: ...
    def lines(self, scene_id: str) -> list[Row]: ...
    def canon(self, production_id: UUID) -> list[Row]: ...
    def lead_persona(self, production_id: UUID) -> Row | None: ...
    def accepted_frames(self, shot_ids: list[str]) -> dict[str, Row]: ...
    def last_prompt_version(self, shot_id: str) -> int: ...
    def techniques(self, query: str, embedding: list[float] | None, k: int = 4) -> list[Row]: ...
    def save_design(self, shot_id: str, ir: Row, design: Row) -> None: ...
    def add_prompt(self, row: Row) -> None: ...
    def audit(self, row: Row) -> None: ...


class JobsLike(Protocol):
    def check(self, payload: DispatchPayload) -> str | None: ...
    def set(self, job_id: UUID, status: JobStatus, **fields: Any) -> None: ...
    def event(self, job_id: UUID, type_: JobEventType, payload: Row, agent: str | None = None) -> None: ...
    def finish(self, payload: DispatchPayload, result: Row, next_state: Row | None = None, *,
               again: bool = False) -> None: ...


class LLMLike(shots.LLMLike, Protocol):
    def embed(self, texts: list[str], *, phase: str) -> list[list[float]]: ...


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _palette(store: StoreLike, llm: LLMLike, scenes: list[SceneInput], targets: set[str] | None) -> str:
    intents = [s.title for sc in scenes for s in sc.shots if s.title and (targets is None or s.id in targets)]
    intents += [sc.heading for sc in scenes]
    return techniques.palette(intents, "Sri Lankan television drama", store.techniques,
                              (lambda q: llm.embed(q, phase="shot_producer.techniques")) if llm.enabled else None)


def design_scene(scene: SceneInput, group: list[ShotInput], prod: ProductionInput, llm: LLMLike,
                 ledger: ContinuityLedger, prefix: str, job_id: str) -> list[tuple[ShotInput, Row, Row]]:
    """→ [(shot, ir, design)] for every shot in `group`, by model where it answered, else by rules."""
    answered = shots.design_by_model(llm, prefix, scene, group, ledger) if llm.enabled else {}
    out = []
    for shot in group:
        entry = answered.get(shot.number)
        planner = "model" if entry else "rules"
        ir, rec, why = shots.finish(entry or shots.design_by_rules(scene, shot), shot, scene, prod)
        design = {"recommended": rec.model_dump(), "rationale": why, "planner": planner,
                  "pins": shot.pins.model_dump(), "designed_at": _now(), "job_id": job_id,
                  "missing": shots.get_schema().missing_keys(ir)}
        out.append((shot, ir, design))
    return out


def write_prompt(shot: ShotInput, scene: SceneInput, prod: ProductionInput, frame: Row | None,
                 job_id: str, actor: str) -> Row:
    """A new prompt version's row, serialized in code from the stored IR."""
    previous = next((s for s in scene.shots if s.number == shot.number - 1), None)
    ctx = serialize.Context(aspect_ratio=prod.aspect_ratio, camera=shot.camera(scene),
                            recommended=shot.recommended(scene), style_note=prod.style_note,
                            previous_code=previous.code if previous else "",
                            carried=carried_state(previous.code, previous.row.get("ir")) if previous else "",
                            has_frame=frame is not None)
    ir = dict(shot.row.get("ir") or {})
    sections = serialize.build_sections(shot, ir, ctx)
    return {"production_id": prod.id, "shot_id": shot.id,
            "sections": [s.model_dump(exclude_none=True) for s in sections], "prose": prompt_text(sections),
            "model": f"{VIDEO_MODEL} · {shot.duration_s} s · {prod.aspect_ratio}", "ir": ir,
            "camera": ctx.camera.model_dump(),
            "checks": [c.model_dump() for c in serialize.prompt_checks(shot, sections, ctx)],
            "frame_id": str(frame["id"]) if frame else None, "pins": shot.pins.model_dump(), "job_id": job_id,
            "created_by": actor}


def run(payload: DispatchPayload, store: StoreLike, jobs: JobsLike, llm: LLMLike) -> Row:
    skip = jobs.check(payload)
    if skip:
        return {"skipped": skip}
    job_id, production_id = payload.job_id, payload.production_id
    assert production_id is not None
    jobs.set(job_id, JobStatus.RUNNING)
    production = store.production(production_id)
    if production is None:
        jobs.set(job_id, JobStatus.DONE, result={"skipped": "production deleted"})
        return {"skipped": "production deleted"}
    state = payload.state
    mode = str(state.get("mode") or "design")
    force = bool(state.get("force"))
    shot_ids = [str(s) for s in state.get("shot_ids") or []]
    targets = set(shot_ids) or None
    scene_ids = [str(s) for s in state.get("scene_ids") or []] or store.shot_scenes(production_id, shot_ids)

    canon = store.canon(production_id)
    prod = production_input(production, canon, store.lead_persona(production_id))
    scenes = []
    for row in store.scenes(production_id, scene_ids):
        sid = str(row["id"])
        scenes.append((row, scene_input(row, store.shots(sid), store.lines(sid), canon, prod)))

    ledger = ContinuityLedger(prod.cast)
    prefix: str | None = None
    designed = prompts = 0
    skipped: list[str] = []
    for row, scene in scenes:
        label = f"Scene {scene.number}"
        group = [s for s in scene.shots if (targets is None or s.id in targets) and (force or design_stale(s, prod))]
        if group:
            if prefix is None and llm.enabled:
                prod.techniques = _palette(store, llm, [sc for _, sc in scenes], targets)
                prefix = shots.production_block(prod)
            jobs.event(job_id, JobEventType.PROGRESS, {"text": f"{label}: designing {len(group)} shots",
                                                       "scene_id": scene.id}, agent=AGENT_DP)
            for shot, ir, design in design_scene(scene, group, prod, llm, ledger, prefix or "", str(job_id)):
                store.save_design(shot.id, ir, design)
                shot.row = {**shot.row, "ir": ir, "design": design}
                designed += 1
                jobs.event(job_id, JobEventType.PROGRESS,
                           {"text": f"{shot.code}: {design['recommended']['lens']} · "
                                    f"{design['recommended']['movement'].lower()}",
                            "shot_id": shot.id, "planner": design["planner"]}, agent=AGENT_DP)
        for shot in scene.shots:
            ledger.observe(scene.id, shot, shot.row.get("ir") or {})

        if mode != "prompt":
            continue
        wanted = [s for s in scene.shots if targets is None or s.id in targets]
        if row.get("status") != "approved":
            skipped += [f"{s.code}: the scene is not approved" for s in wanted]
            continue
        frames = store.accepted_frames([s.id for s in wanted])
        for shot in wanted:
            frame = frames.get(shot.id)
            if shot.frame_strategy != "carry_last_frame" and frame is None:
                skipped.append(f"{shot.code}: no accepted first frame")
                continue
            prompt = write_prompt(shot, scene, prod, frame, str(job_id), str(payload.actor_user_id))
            prompt["version"] = store.last_prompt_version(shot.id) + 1
            store.add_prompt(prompt)
            prompts += 1
            jobs.event(job_id, JobEventType.PROGRESS, {"text": f"{shot.code}: prompt v{prompt['version']} written",
                                                       "shot_id": shot.id}, agent=AGENT_PROMPT)
    for note in skipped:
        jobs.event(job_id, JobEventType.WARNING, {"text": note}, agent=AGENT_PROMPT)

    result: Row = {"designed": designed, "prompts": prompts, "skipped": len(skipped)}
    if designed or prompts:
        store.audit({"production_id": str(production_id), "actor_user_id": str(payload.actor_user_id),
                     "actor_agent": "shot_producer", "action": f"shots.{mode}", "entity": "job",
                     "entity_id": str(job_id), "diff": result})
    hand_on = {k: v for k, v in state.items() if k not in ("mode", "force", "previous")}
    jobs.finish(payload, result, hand_on)
    return result
