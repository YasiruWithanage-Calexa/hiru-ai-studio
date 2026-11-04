"""script_split: scenes -> shot lists. The last hop of the structure build, and the director's "Re-split". Ported from
`script_split/engine/pipeline.py`.

For each scene: script blocks + lines -> read each block as a picture (`beat_finder`) -> the scene's reading
(`scene_reader`) -> where its people are (`stager`) -> the rules' plan, then the model's (`scene_planner`) -> the
`plan_review` panel (three critics write notes, ONE revision, the kernel score in code picks) -> the rules' plan once
more as a rival -> shots written, lines bound to shots and beats, the fit report stored on the scene. An APPROVED scene
is never touched.

    load   the scenes to plan (approved ones and ones with no script are skipped)
    plan   waves of four scenes planned in parallel and written one at a time; past the time budget the rest go to a
           fresh delivery of this hop (the function deadline is fixed; a long drama can need more than one)
    wrap   totals; the next delivery, or the episodes' status and the build log

Idempotent: a scene's shots are replaced, never appended, and its lines are re-bound in place. A missing key or a
failing model never stops a scene: the rules plan it.
"""
from __future__ import annotations

import contextvars
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from contracts import reading as scene_reading
from contracts import sceneplan, stagemap
from contracts.build import Agent, Stage
from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from contracts.production import ProductionSettings
from contracts.shotplan import FitResult, Item, ProposedShot, allowed_durations, fit
from hiru_ai.core import agents, llm, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.panels import PanelKit
from hiru_ai.core.registry import Registry
from hiru_ai.systems.script_split.state import State

_log = logging.getLogger(__name__)
AGENT = Agent.PLANNER.value
PLAN_WORKERS = 4
TITLE_CHARS = 80
TIME_BUDGET_S = 420.0  # of the 900 s deadline: a wave of model calls can take minutes
Row = dict[str, Any]


def _plain(out: Any) -> Row:
    return dict(out.model_dump(mode="json"))


def build(ctx: RunContext, payload: DispatchPayload, production: Row, *,
          budget_s: float | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    jobs, scenes_port, split = ctx.need("jobs"), ctx.need("scenes"), ctx.need("split")
    job_id, production_id = payload.job_id, payload.production_id
    assert production_id is not None
    prep, rules, write = parts.step("scene_prep"), parts.step("rules_plan"), parts.step("split_write")
    kernel, listing = parts.step("kernel_score"), parts.step("scene_listing")
    plan_review = parts.module("panel", "plan_review", "graph")
    settings = ProductionSettings.model_validate(production.get("settings") or {})
    fixed = settings.fixed_shot_seconds
    enabled = llm.models_enabled()
    started = time.monotonic()
    limit = TIME_BUDGET_S if budget_s is None else budget_s

    characters = split.characters(production_id)
    names = {str(c["id"]): str(c["name"]) for c in characters}
    cast = list(names.values())
    cards = [(str(c["name"]), str(((c.get("current") or {}).get("card") or {}).get("summary") or ""))
             for c in characters]
    episode_rows = {str(e["id"]): e for e in split.episodes(production_id)}
    episode_no = {k: int(e["number"]) for k, e in episode_rows.items()}
    neighbours = split.neighbours(production_id)
    places = prep.location_notes(split.locations(production_id))

    # What each scene turns into while it is planned in a worker; the writing happens in the main thread.
    scripts: dict[str, list[Row]] = {}  # scene id -> its script with implied steps and readings
    readings: dict[str, scene_reading.SceneReading] = {}
    stagings: dict[str, stagemap.SceneStaging] = {}
    staging_reports: dict[str, Row] = {}

    # ── asking the agents ──────────────────────────────────────────────────────────────────────────────────────────

    def ask_beats(items: list[Item]) -> Row:
        return _plain(agents.build("beat_finder").run({"items": items}, ctx))

    def reading_ask(context: Row) -> Any:
        def ask(items: list[Item]) -> Row:
            return _plain(agents.build("scene_reader").run(
                {"items": items, "speaker_names": names, "context": context}, ctx))

        return ask

    def staging_ask(reading: scene_reading.SceneReading, place: str) -> Any:
        def ask(items: list[Item]) -> Row:
            return _plain(agents.build("stager").run(
                {"items": items, "speaker_names": names, "reading_text": reading.text() if reading else "",
                 "place": place}, ctx))

        return ask

    # ── planning one scene ─────────────────────────────────────────────────────────────────────────────────────────

    def plan_scene(items: list[Item], *, heading: str, envelope_s: int, reading: scene_reading.SceneReading,
                   context: Row, staging: stagemap.SceneStaging | None) -> tuple[FitResult, str, list[str]]:
        """-> (fitted plan, which planner, critic notes acted on).

        `items` carry the reading's time. Over the envelope, optional breath is given up first; the plan, the rules' and
        the model's, is fitted and scored with what is left, and the result says what was given up. Three model critics
        write notes; the kernel score in code, which also weighs the staging map's checks, picks the plan."""
        base = list(items)
        items, rules_shots = rules.rules_plan(base, envelope_s=envelope_s, fixed_seconds=fixed)
        rules_result = fit(items, rules_shots, envelope_s=envelope_s, fixed_seconds=fixed)

        def finish(result: FitResult, used: str, notes: list[str]) -> tuple[FitResult, str, list[str]]:
            return write.with_breath(result, base, items, envelope_s, fixed), used, notes

        if not enabled or not items:
            return finish(rules_result, "rules", [])
        reading_text = reading.text() if reading else ""
        plan_input = {"items": items, "speaker_names": names, "heading": heading, "envelope_s": envelope_s,
                      "allowed": list(allowed_durations(fixed)), "context": prep.context_text(context),
                      "reading": reading_text}

        def score(result: FitResult) -> Any:
            return kernel.kernel_score(result, reading, items, staging, cast)

        try:
            out = agents.build("scene_planner").run(plan_input, ctx)
            if not out.shots:
                raise ValueError("the planner returned no shots")
            best = fit(items, [ProposedShot(s.start, s.end, s.framing, s.title[:TITLE_CHARS], s.sound_mode, s.duration,
                                            False, s.camera_link) for s in out.shots],
                       envelope_s=envelope_s, fixed_seconds=fixed)
        except Exception:
            _log.warning("model planner failed; using the rules", exc_info=True)
            return finish(rules_result, "rules", [])
        notes: list[str] = []
        try:
            found = [f.message for f in stagemap.checks(staging, items, best, cast)]
            brief = {"items": items, "reading": reading, "staging": staging, "cast": cast,
                     "listing": listing.scene_listing(items, names), "reading_text": reading_text,
                     "staging_text": staging.text() if staging else "", "found": found, "plan_input": plan_input,
                     "envelope_s": envelope_s, "fixed_seconds": fixed}
            panel = plan_review.build(ctx)
            out_state = panel.invoke({"brief": brief, "candidates": [best],
                                      "lenses": plan_review.lenses(PanelKit(plan_review.ID, ctx))})
            notes = list(out_state.get("notes") or [])
            best = out_state["candidates"][out_state["winner"]]  # a revision replaces the first plan only if better
        except Exception:
            _log.warning("critic round failed; keeping the first plan", exc_info=True)
        if score(rules_result) < score(best):
            return finish(rules_result, "rules", notes)  # the model's plan broke more than the rules' did
        return finish(best, "model", notes)

    def plan_one(job: Row) -> tuple[FitResult, str, list[str]]:
        scene, lines = job["scene"], job["lines"]
        sid = str(scene["id"])
        scripts[sid], items = prep.prepare(scene, lines, ask_beats if enabled else None, cast)
        context = prep.scene_context(scene, episode_rows, neighbours, cards)
        reading, _ = prep.reading_for(scene, items, reading_ask(context) if enabled else None, cast)
        place = places.get(str(scene.get("location_id")), "")
        script, items, reading, staging = prep.stage(scene, lines, scripts[sid], items, reading,
                                                     staging_ask(reading, place) if enabled else None, names)
        scripts[sid] = script
        reading = scene_reading.clear_envelope(reading)
        timed = scene_reading.apply(items, reading)
        result, used, notes = plan_scene(timed, heading=scene["heading"], envelope_s=int(scene["envelope_s"]),
                                         reading=reading, context=context, staging=staging)
        readings[sid] = scene_reading.mark_off(reading, timed, result.breath_dropped)
        if staging is not None:
            stagings[sid] = staging
            found = stagemap.checks(staging, timed, result, cast)
            staging_reports[sid] = write.staging_report(staging, timed, found, cast)
        return result, used, notes

    # ── the graph ──────────────────────────────────────────────────────────────────────────────────────────────────

    def load(state: State) -> State:
        carried: Row = dict(payload.state.get("progress") or {})
        scene_ids = payload.state.get("scene_ids")
        rows = scenes_port.scenes(production_id, [str(s) for s in scene_ids] if scene_ids is not None else None)
        if not carried:
            jobs.stage(job_id, Stage.SHOTS.value, "active", f"Planning shots for {len(rows)} scenes")
        todo: list[Row] = []
        skipped = 0
        for scene in rows:
            label = f"Ep {episode_no.get(str(scene['episode_id']), 0):02d} Scene {scene['number']}"
            if scene["status"] == "approved":
                skipped += 1
                jobs.event(job_id, JobEventType.PROGRESS, {"text": f"{label} is approved; left as it is"}, agent=AGENT)
                continue
            lines = scenes_port.lines(UUID(str(scene["id"])))
            if not sceneplan.items_for(scene.get("script") or [], lines):
                skipped += 1
                continue
            todo.append({"label": label, "scene": scene, "lines": lines})
        return {"todo": todo, "skipped": skipped, "carried": carried}

    def plan(state: State) -> State:
        todo, carried = state["todo"], state["carried"]
        continuity: list[str] = list(carried.get("continuity") or [])
        episodes: dict[str, dict[str, int]] = {k: dict(v) for k, v in (carried.get("episodes") or {}).items()}
        written = shot_count = issues = 0
        left: list[Row] = []
        # Scenes are planned in parallel waves (model calls dominate) and written here, one at a time.
        workers = PLAN_WORKERS if enabled else 1
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for i in range(0, len(todo), workers):
                if i and time.monotonic() - started > limit:
                    left = todo[i:]
                    break
                wave = todo[i: i + workers]
                copies = [contextvars.copy_context() for _ in wave]  # copied here, in this thread, one per task
                planned = pool.map(lambda pair: pair[0].run(plan_one, pair[1]), zip(copies, wave, strict=True))
                for job, (result, used, notes) in zip(wave, planned, strict=True):
                    scene, lines, label = job["scene"], job["lines"], job["label"]
                    sid = str(scene["id"])
                    shots, line_rows = write.rows_for(scene, result, lines)
                    fields: Row = {"status": "split", "fit_report": write.report(result, used, notes)}
                    if sid in staging_reports:
                        fields["fit_report"]["staging"] = staging_reports[sid]
                    if scripts[sid] != (scene.get("script") or []):
                        fields["script"] = scripts[sid]  # implied steps and readings, with the shots
                    fields["reading"] = readings[sid].model_dump(mode="json")
                    if sid in stagings:  # no map (no key) leaves a stored one as it is
                        fields["staging"] = stagings[sid].model_dump(mode="json")
                    scenes_port.replace_shots(UUID(sid), shots, line_rows, fields)
                    continuity.extend(write.continuity_notes(label, scene, lines))
                    written += 1
                    shot_count += len(shots)
                    issues += parts.step("kernel_score").issue_count(result)
                    tally = episodes.setdefault(str(episode_no.get(str(scene["episode_id"]), 0)),
                                                dict.fromkeys(write.EPISODE_KEYS, 0))
                    for key, value in write.episode_stats(result, scene).items():
                        tally[key] = tally.get(key, 0) + value
                    jobs.event(job_id, JobEventType.PROGRESS,
                               {"text": f"{label}: {len(shots)} shots, {result.total_s} s",
                                "scene_id": sid, "shots": len(shots), "total_s": result.total_s,
                                "issues": len(result.issues)}, agent=AGENT)
        return {"written": written, "shot_count": shot_count, "issues": issues, "continuity": continuity,
                "episodes": episodes, "left": [str(job["scene"]["id"]) for job in left]}

    def wrap(state: State) -> State:
        carried = state["carried"]
        totals = {"scenes": state["written"] + int(carried.get("scenes", 0)),
                  "skipped": state["skipped"] + int(carried.get("skipped", 0)),
                  "shots": state["shot_count"] + int(carried.get("shots", 0)),
                  "issues": state["issues"] + int(carried.get("issues", 0))}
        left, continuity, episodes = state["left"], state["continuity"], state["episodes"]
        if left:
            jobs.event(job_id, JobEventType.PROGRESS, {"text": f"{len(left)} scenes left; continuing"}, agent=AGENT)
            jobs.finish(payload, totals, {"build": bool(payload.state.get("build")), "scene_ids": left,
                                          "progress": {**totals, "continuity": continuity[:50],
                                                       "episodes": episodes}}, again=True)
            return {"result": {**totals, "continued": len(left)}}
        jobs.stage(job_id, Stage.SHOTS.value, "done", f"{totals['shots']} shots in {totals['scenes']} scenes")

        # Episodes whose scenes all have shots are ready for the Director panel.
        by_episode: dict[str, list[str]] = {}
        for row in split.scene_status(production_id):
            by_episode.setdefault(str(row["episode_id"]), []).append(str(row["status"]))
        for episode_id, statuses in by_episode.items():
            if statuses and all(s in ("split", "approved") for s in statuses):
                split.set_episode_status(episode_id, "approved" if all(s == "approved" for s in statuses) else "ready")

        if payload.state.get("build"):
            for number in sorted(episodes, key=int):
                jobs.event(job_id, JobEventType.AGENT_STEP,
                           {"text": write.episode_line(int(number), episodes[number])}, agent=AGENT)
            jobs.stage(job_id, Stage.CONTINUITY.value, "active")
            for note in continuity[:20]:
                jobs.event(job_id, JobEventType.WARNING, {"text": note}, agent=Agent.CONTINUITY.value)
            jobs.stage(job_id, Stage.CONTINUITY.value, "done",
                       f"{len(continuity)} things to check" if continuity else "No problems found")
            jobs.stage(job_id, Stage.REVIEW.value, "active", "Ready for your review")

        jobs.finish(payload, totals)
        return {"result": totals}

    g: Any = StateGraph(State)
    for name, node in (("load", load), ("plan", plan), ("wrap", wrap)):
        g.add_node(name, node)
    g.add_edge(START, "load")
    g.add_edge("load", "plan")
    g.add_edge("plan", "wrap")
    g.add_edge("wrap", END)
    return g.compile()


def run(payload: DispatchPayload, ctx: RunContext, *, budget_s: float | None = None) -> dict[str, Any]:
    jobs, scenes = ctx.need("jobs"), ctx.need("scenes")
    skip = jobs.check(payload)
    if skip:
        return {"skipped": skip}
    production_id = payload.production_id
    assert production_id is not None
    jobs.set(payload.job_id, JobStatus.RUNNING)
    production = scenes.production(production_id)
    if production is None:
        jobs.set(payload.job_id, JobStatus.DONE, result={"skipped": "production deleted"})
        return {"skipped": "production deleted"}
    result: dict[str, Any] = build(ctx, payload, production, budget_s=budget_s).invoke({})["result"]
    return result


def blank(registry: Registry | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    """The graph with nothing to run, for drawing and for the generated contract tests."""
    from dataclasses import replace
    from uuid import uuid4

    from contracts.jobs import JobKind
    from hiru_ai.core.context import Ports
    from hiru_ai.core.fakes import FakeJobs, FakeScenes, FakeSplit

    ports = replace(Ports(), jobs=FakeJobs(), scenes=FakeScenes(), split=FakeSplit())
    payload = DispatchPayload(job_id=uuid4(), kind=JobKind.SCRIPT_SPLIT, actor_user_id=uuid4(), production_id=uuid4())
    return build(RunContext(ports=ports), payload, {"id": str(uuid4()), "settings": {}})
