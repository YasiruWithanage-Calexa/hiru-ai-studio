"""Scenes → shot lists. The last hop of the structure build, and the director's "Re-split".

For each scene: script blocks + lines → a planner proposes → the kernel fits → the critic
reviews (one bounded re-plan) → shots written, lines bound to shots and beats, the fit report
stored on the scene. An APPROVED scene is never touched.

Idempotent: a scene's shots are replaced, never appended, and its lines are re-bound in place.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol
from uuid import UUID, uuid4

from contracts.build import Agent, Stage
from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from contracts.production import ProductionSettings
from contracts.shotplan import FitResult, Item, allowed_durations, fit
from script_split.engine import critic, planner

_logger = logging.getLogger(__name__)
AGENT = Agent.PLANNER.value
PLAN_WORKERS = 4
TIME_BUDGET_S = 420.0  # of the 900 s deadline: a wave of model calls can take minutes


class StoreLike(Protocol):
    def production(self, production_id: UUID) -> dict[str, Any] | None: ...
    def scenes(self, production_id: UUID, scene_ids: list[str] | None) -> list[dict[str, Any]]: ...
    def episodes(self, production_id: UUID) -> list[dict[str, Any]]: ...
    def lines(self, scene_id: UUID) -> list[dict[str, Any]]: ...
    def characters(self, production_id: UUID) -> list[dict[str, Any]]: ...
    def scene_status(self, production_id: UUID) -> list[dict[str, Any]]: ...
    def replace_shots(self, scene_id: UUID, shots: list[dict[str, Any]], lines: list[dict[str, Any]],
                      scene_fields: dict[str, Any]) -> None: ...
    def set_episode_status(self, episode_id: str, status: str) -> None: ...


class JobsLike(Protocol):
    def check(self, payload: DispatchPayload) -> str | None: ...
    def set(self, job_id: UUID, status: JobStatus, **fields: Any) -> None: ...
    def event(self, job_id: UUID, type_: JobEventType, payload: dict[str, Any], agent: str | None = None) -> None: ...
    def stage(self, job_id: UUID, stage: str, state: str, text: str = "") -> None: ...
    def finish(self, payload: DispatchPayload, result: dict[str, Any],
               next_state: dict[str, Any] | None = None, *, again: bool = False) -> None: ...


class LLMLike(Protocol):
    @property
    def enabled(self) -> bool: ...
    def json(self, *, tier: str, phase: str, system: str, user: str, schema_name: str,
             schema: dict[str, Any]) -> dict[str, Any]: ...


def items_for(scene: dict[str, Any], lines: list[dict[str, Any]]) -> list[Item]:
    by_id = {str(ln["id"]): ln for ln in lines}
    items: list[Item] = []
    for block in scene.get("script") or []:
        kind = str(block.get("kind", "action"))
        line = by_id.get(str(block.get("line_id"))) if kind == "dialogue" else None
        if kind == "dialogue" and line is None:
            continue  # a dangling reference (line deleted): nothing to bind
        if line is not None:
            items.append(Item(len(items), "dialogue", line["text"], line["speaker"],
                              str(line["character_id"]) if line.get("character_id") else None,
                              line.get("delivery") or "", str(line["id"])))
        else:
            items.append(Item(len(items), kind, str(block.get("text", ""))))
    return items


def continuity_notes(label: str, scene: dict[str, Any], lines: list[dict[str, Any]]) -> list[str]:
    """Free checks a person should see before directing: a scene with no place, a line nobody
    in the canon speaks, a scene with no script."""
    notes = []
    if not scene.get("location_id"):
        notes.append(f"{label} has no location; frames cannot be matched to a set.")
    unknown = sorted({str(ln["speaker"]) for ln in lines if not ln.get("character_id")})
    if unknown:
        notes.append(f"{label}: {', '.join(unknown)} not linked to a canon character, so no voice pin.")
    if not scene.get("script"):
        notes.append(f"{label} has no script.")
    return notes


def plan_scene(items: list[Item], *, heading: str, envelope_s: int, fixed: int | None, llm: LLMLike,
               speaker_names: dict[str, str]) -> tuple[FitResult, str, list[str]]:
    """→ (fitted plan, which planner, critic notes acted on)."""
    rules = fit(items, planner.plan_by_rules(items), envelope_s=envelope_s, fixed_seconds=fixed)
    if not llm.enabled or not items:
        return rules, "rules", []
    allowed = allowed_durations(fixed)

    def ask_plan(system: str, user: str) -> dict[str, Any]:
        return llm.json(tier="high", phase="script_split.plan", system=system, user=user,
                        schema_name="shot_plan", schema=planner.PLAN_SCHEMA)

    def ask_critic(system: str, user: str) -> dict[str, Any]:
        return llm.json(tier="medium", phase="script_split.critic", system=system, user=user,
                        schema_name="shot_review", schema=critic.CRITIC_SCHEMA)

    try:
        proposal = planner.plan_by_model(ask_plan, items, heading=heading, envelope_s=envelope_s,
                                         allowed=allowed, speaker_names=speaker_names)
        best = fit(items, proposal, envelope_s=envelope_s, fixed_seconds=fixed)
    except Exception:
        _logger.warning("model planner failed; using the rules", exc_info=True)
        return rules, "rules", []
    notes: list[str] = []
    try:
        notes = critic.review(ask_critic, planner.scene_listing(items, speaker_names), best, items)
        if notes:
            revised = fit(items, planner.plan_by_model(ask_plan, items, heading=heading, envelope_s=envelope_s,
                                                       allowed=allowed, speaker_names=speaker_names, notes=notes),
                          envelope_s=envelope_s, fixed_seconds=fixed)
            if critic.kernel_score(revised) <= critic.kernel_score(best):
                best = revised
    except Exception:
        _logger.warning("critic round failed; keeping the first plan", exc_info=True)
    if critic.kernel_score(rules) < critic.kernel_score(best):
        return rules, "rules", notes  # the model's plan broke more than the rules' did
    return best, "model", notes


Rows = list[dict[str, Any]]


def rows_for(scene: dict[str, Any], result: FitResult, lines: Rows) -> tuple[Rows, Rows]:
    shot_ids = {s.number: str(uuid4()) for s in result.shots}
    shots = [{
        "id": shot_ids[s.number], "production_id": scene["production_id"], "scene_id": scene["id"],
        "number": s.number, "title": s.title, "framing": s.framing, "duration_s": s.duration_s,
        "start_s": s.start_s, "sound_mode": s.sound_mode.value, "camera_link": s.camera_link.value,
        "frame_strategy": s.frame_strategy.value, "speaker_id": s.speaker_id,
        "beats": [{"start_s": b0, "end_s": b1, "camera": "", "director_line": "", "action": ""} for b0, b1 in s.beats],
        "block_start": s.start, "block_end": s.end, "word_target": s.word_target, "words": s.words,
        "status": "draft", "version": 1,
    } for s in result.shots]
    fitted = {fl.line_id: fl for fl in result.lines}
    keep = ("id", "production_id", "scene_id", "ord", "speaker", "character_id", "text", "delivery")
    line_rows = []
    for ln in lines:
        fl = fitted.get(str(ln["id"]))
        row = {k: ln.get(k) for k in keep}
        row.update({"words": fl.words if fl else 0, "shot_id": shot_ids[fl.shot_number] if fl else None,
                    "beat_index": fl.beat_index if fl else None, "start_s": fl.start_s if fl else None,
                    "overrun_s": fl.overrun_s if fl else 0})
        line_rows.append(row)
    return shots, line_rows


def report(result: FitResult, planner_name: str, notes: list[str]) -> dict[str, Any]:
    return {"total_s": result.total_s, "envelope_s": result.envelope_s, "planner": planner_name,
            "critic_notes": notes,
            "issues": [{"code": i.code, "message": i.message, "shot": i.shot_number, "line_id": i.line_id}
                       for i in result.issues]}


def run(payload: DispatchPayload, store: StoreLike, jobs: JobsLike, llm: LLMLike) -> dict[str, Any]:
    skip = jobs.check(payload)
    if skip:
        return {"skipped": skip}
    job_id = payload.job_id
    production_id = payload.production_id
    assert production_id is not None
    jobs.set(job_id, JobStatus.RUNNING)
    production = store.production(production_id)
    if production is None:
        jobs.set(job_id, JobStatus.DONE, result={"skipped": "production deleted"})
        return {"skipped": "production deleted"}
    settings = ProductionSettings.model_validate(production.get("settings") or {})
    fixed = settings.fixed_shot_seconds
    scene_ids = payload.state.get("scene_ids")
    scenes = store.scenes(production_id, [str(s) for s in scene_ids] if scene_ids is not None else None)
    episode_no = {str(e["id"]): int(e["number"]) for e in store.episodes(production_id)}
    names = {str(c["id"]): str(c["name"]) for c in store.characters(production_id)}

    # Totals carried from earlier deliveries of this hop (a long build runs in time-boxed batches).
    carried: dict[str, Any] = dict(payload.state.get("progress") or {})
    if not carried:
        jobs.stage(job_id, Stage.SHOTS.value, "active", f"Planning shots for {len(scenes)} scenes")
    started = time.monotonic()
    written = skipped = shot_count = issues = 0
    continuity: list[str] = list(carried.get("continuity") or [])
    todo: list[tuple[str, dict[str, Any], list[dict[str, Any]], list[Item]]] = []
    for scene in scenes:
        label = f"Ep {episode_no.get(str(scene['episode_id']), 0):02d} Scene {scene['number']}"
        if scene["status"] == "approved":
            skipped += 1
            jobs.event(job_id, JobEventType.PROGRESS, {"text": f"{label} is approved; left as it is"}, agent=AGENT)
            continue
        lines = store.lines(UUID(str(scene["id"])))
        items = items_for(scene, lines)
        if not items:
            skipped += 1
            continue
        todo.append((label, scene, lines, items))

    def plan_one(job: tuple[str, dict[str, Any], list[dict[str, Any]], list[Item]]) -> tuple[FitResult, str, list[str]]:
        _, scene, _, items = job
        return plan_scene(items, heading=scene["heading"], envelope_s=int(scene["envelope_s"]), fixed=fixed,
                          llm=llm, speaker_names=names)

    # Scenes are planned in parallel waves (model calls dominate) and written here, one at a time.
    # Past the time budget, the scenes left go to a fresh delivery of this hop (the function
    # deadline is fixed; a long drama can need more than one).
    workers = PLAN_WORKERS if llm.enabled else 1
    left: list[tuple[str, dict[str, Any], list[dict[str, Any]], list[Item]]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i in range(0, len(todo), workers):
            if i and time.monotonic() - started > TIME_BUDGET_S:
                left = todo[i:]
                break
            wave = todo[i: i + workers]
            for (label, scene, lines, _), (result, used, notes) in zip(wave, pool.map(plan_one, wave), strict=True):
                shots, line_rows = rows_for(scene, result, lines)
                store.replace_shots(UUID(str(scene["id"])), shots, line_rows,
                                    {"status": "split", "fit_report": report(result, used, notes)})
                continuity.extend(continuity_notes(label, scene, lines))
                written += 1
                shot_count += len(shots)
                issues += critic.kernel_score(result)
                jobs.event(job_id, JobEventType.PROGRESS,
                           {"text": f"{label}: {len(shots)} shots, {result.total_s} s",
                            "scene_id": str(scene["id"]), "shots": len(shots), "total_s": result.total_s,
                            "issues": len(result.issues)}, agent=AGENT)

    totals = {"scenes": written + int(carried.get("scenes", 0)), "skipped": skipped + int(carried.get("skipped", 0)),
              "shots": shot_count + int(carried.get("shots", 0)), "issues": issues + int(carried.get("issues", 0))}
    if left:
        jobs.event(job_id, JobEventType.PROGRESS, {"text": f"{len(left)} scenes left; continuing"}, agent=AGENT)
        jobs.finish(payload, totals, {"build": bool(payload.state.get("build")),
                                      "scene_ids": [str(sc["id"]) for _, sc, _, _ in left],
                                      "progress": {**totals, "continuity": continuity[:50]}}, again=True)
        return {**totals, "continued": len(left)}
    jobs.stage(job_id, Stage.SHOTS.value, "done", f"{totals['shots']} shots in {totals['scenes']} scenes")

    # Episodes whose scenes all have shots are ready for the Director panel.
    by_episode: dict[str, list[str]] = {}
    for row in store.scene_status(production_id):
        by_episode.setdefault(str(row["episode_id"]), []).append(str(row["status"]))
    for episode_id, statuses in by_episode.items():
        if statuses and all(s in ("split", "approved") for s in statuses):
            store.set_episode_status(episode_id, "approved" if all(s == "approved" for s in statuses) else "ready")

    if payload.state.get("build"):
        jobs.stage(job_id, Stage.CONTINUITY.value, "active")
        for note in continuity[:20]:
            jobs.event(job_id, JobEventType.WARNING, {"text": note}, agent=Agent.CONTINUITY.value)
        jobs.stage(job_id, Stage.CONTINUITY.value, "done",
                   f"{len(continuity)} things to check" if continuity else "No problems found")
        jobs.stage(job_id, Stage.REVIEW.value, "active", "Ready for your review")

    jobs.finish(payload, totals)
    return totals
