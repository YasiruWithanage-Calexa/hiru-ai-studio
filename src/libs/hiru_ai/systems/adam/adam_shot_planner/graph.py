"""adam_shot_planner: scenes -> shot cards -> `shots` rows. The last hop of the structure build when the production's
`shot_planner` setting says `adam`, and the director's "Plan with Adam" (plan/2026-11-04b §5.5).

For each scene: its script and lines become Adam's scene (people present, the place and what it has), `scene.Planner`
runs the stages (analyse, conceive, imagine, stage, design, screen), and `adam_write` turns the winner into rows. An
APPROVED scene is never touched.

    load   the scenes to plan (approved ones and ones with no script are skipped)
    plan   waves of four scenes planned in parallel and written one at a time; past the time budget the rest go to a
           fresh delivery of this hop (the function deadline is fixed)
    wrap   totals; the next delivery, or the episodes' status and the build log

A delivery can also carry an EDIT for one scene (`state.edit`): `{"remove_moment": "m5"}` takes an elaboration out
(no model is called; the same addition never comes back) and `{"treatment": "heightened"}` plans the cards again
from the stored analysis under another treatment. Idempotent: a scene's shots are replaced, never appended. With no
model the job fails clearly and says to use the classic planner: Adam has no rules fallback worth having.
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

from contracts import sceneplan
from contracts.adam.stored import StoredPlan
from contracts.build import Agent, Stage
from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from contracts.production import ProductionSettings
from hiru_ai.core import llm, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.registry import Registry
from hiru_ai.systems.adam.adam_shot_planner import scene as adam
from hiru_ai.systems.adam.adam_shot_planner.state import State

_log = logging.getLogger(__name__)
AGENT = Agent.PLANNER.value
PLAN_WORKERS = 4
TIME_BUDGET_S = 420.0  # of the 900 s deadline: a scene is about eleven model calls
PLAN_WITH_TRIMS = True  # plan/2026-11-04c D3: plans carry their editorial trims whatever the final cut is set to
Row = dict[str, Any]


def previous_of(shots: list[Row], stored: StoredPlan | None) -> Row:
    """The shot list to keep for a side-by-side look: what the scene had before Adam first planned it."""
    if stored is not None and stored.previous:
        return stored.previous
    classic = [s for s in shots if s.get("planner", "classic") != "adam"]
    keys = ("number", "title", "framing", "duration_s", "sound_mode", "camera_link", "block_start", "block_end",
            "words")
    return {"planner": "classic", "shots": [{k: s.get(k) for k in keys} for s in classic]} if classic else {}


def build(ctx: RunContext, payload: DispatchPayload, production: Row, *,
          budget_s: float | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    jobs, scenes_port, split = ctx.need("jobs"), ctx.need("scenes"), ctx.need("split")
    job_id, production_id = payload.job_id, payload.production_id
    assert production_id is not None
    write = parts.step("adam_write", "step")
    started = time.monotonic()
    limit = TIME_BUDGET_S if budget_s is None else budget_s
    edit: Row = dict(payload.state.get("edit") or {})
    # Plan/2026-11-04c D3: Adam plans with the editorial trims on (a 2 s reaction cut from a 4 s take costs 2 s), so a
    # dense plan is not charged 4 s a cut. The final cut applies them only when the production's setting is on.
    editorial = PLAN_WITH_TRIMS or ProductionSettings.model_validate(production.get("settings") or {}).final_cut_trim

    characters = split.characters(production_id)
    cards = {str(c["name"]): str(((c.get("current") or {}).get("card") or {}).get("summary") or "")
             for c in characters}
    people = {str(c["name"]): str(c["id"]) for c in characters}  # for the shot intent: who is in frame, who is heard
    episode_rows = {str(e["id"]): e for e in split.episodes(production_id)}
    episode_no = {k: int(e["number"]) for k, e in episode_rows.items()}
    neighbours = split.neighbours(production_id)
    locations = {str(r["id"]): r for r in split.locations(production_id)}
    props = [c for c in scenes_port.canon(production_id) if c.get("kind") == "prop"]

    def gist(row: Row | None) -> str:
        return " — ".join(p for p in (str((row or {}).get("heading") or ""), str((row or {}).get("title") or "")) if p)

    def surrounding(sc: Row) -> tuple[str, str]:
        sibs = sorted((n for n in neighbours if str(n.get("episode_id")) == str(sc.get("episode_id"))),
                      key=lambda n: int(n.get("number") or 0))
        number = int(sc.get("number") or 0)
        before = next((n for n in reversed(sibs) if int(n.get("number") or 0) < number), None)
        after = next((n for n in sibs if int(n.get("number") or 0) > number), None)
        return gist(before), gist(after)

    # ── planning one scene (in a worker; the writing happens in the main thread) ───────────────

    def plan_one(job: Row) -> adam.Planned | str:
        scene, lines = job["scene"], job["lines"]
        stored = StoredPlan.load(scene.get("adam"))
        bare, _ = adam.script_of(scene, lines, cast=[], place="", objects=[])
        cast = adam.present(characters, bare.blocks)
        location = locations.get(str(scene.get("location_id")))
        place = str((location or {}).get("name") or scene.get("heading") or "")
        script, line_ids = adam.script_of(scene, lines, cast=cast, place=place,
                                          objects=adam.objects_of(props, location, bare.blocks))
        before, after = surrounding(scene)
        context = adam.context_of(scene, episode_rows.get(str(scene.get("episode_id"))) or {}, before, after,
                                  [(n, cards.get(n, "")) for n in cast])
        planner = adam.Planner(ctx, script, context=context, line_ids=line_ids,
                               removed=list(stored.removed) if stored else [],
                               screening=bool(payload.state.get("screening", True)), editorial=editorial)
        try:
            if "remove_moment" in edit:
                if stored is None:
                    return "This scene was not planned by Adam, so there is nothing to remove from."
                return planner.remove_moment(stored, str(edit["remove_moment"]), str(job_id))
            return planner.plan(stance=str(edit.get("treatment") or ""), resume=stored if edit.get("treatment")
                                else None, previous=previous_of(scenes_port.shots(UUID(str(scene["id"]))), stored),
                                job_id=str(job_id))
        except adam.Failed as failure:
            return str(failure)

    # ── the graph ──────────────────────────────────────────────────────────────────────────────

    def load(state: State) -> State:
        carried: Row = dict(payload.state.get("progress") or {})
        scene_ids = payload.state.get("scene_ids")
        rows = scenes_port.scenes(production_id, [str(s) for s in scene_ids] if scene_ids is not None else None)
        if not carried:
            jobs.stage(job_id, Stage.SHOTS.value, "active", f"Planning shots for {len(rows)} scenes with Adam")
        todo: list[Row] = []
        skipped = 0
        for sc in rows:
            label = f"Ep {episode_no.get(str(sc['episode_id']), 0):02d} Scene {sc['number']}"
            if sc["status"] == "approved":
                skipped += 1
                jobs.event(job_id, JobEventType.PROGRESS, {"text": f"{label} is approved; left as it is"}, agent=AGENT)
                continue
            lines = scenes_port.lines(UUID(str(sc["id"])))
            if not sceneplan.items_for(sc.get("script") or [], lines):
                skipped += 1
                continue
            todo.append({"label": label, "scene": sc, "lines": lines})
        return {"todo": todo, "skipped": skipped, "carried": carried}

    def plan(state: State) -> State:
        todo, carried = state["todo"], state["carried"]
        notes: list[str] = list(carried.get("notes") or [])
        failed: list[Row] = list(carried.get("failed") or [])
        episodes: dict[str, int] = {k: int(v) for k, v in (carried.get("episodes") or {}).items()}
        written = shot_count = 0
        left: list[Row] = []
        workers = PLAN_WORKERS if len(todo) > 1 else 1
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for i in range(0, len(todo), workers):
                if i and time.monotonic() - started > limit:
                    left = todo[i:]
                    break
                wave = todo[i: i + workers]
                copies = [contextvars.copy_context() for _ in wave]  # copied here, in this thread, one per task
                planned = pool.map(lambda pair: pair[0].run(plan_one, pair[1]), zip(copies, wave, strict=True))
                for job, result in zip(wave, planned, strict=True):
                    sc, label = job["scene"], job["label"]
                    if isinstance(result, str):
                        failed.append({"scene_id": str(sc["id"]), "label": label, "reason": result})
                        jobs.event(job_id, JobEventType.WARNING, {"text": f"{label}: {result}"}, agent=AGENT)
                        continue
                    out = write.run({"scene": sc, "lines": job["lines"], "stored": result.stored.data(),
                                     "fit": result.fit, "notes": result.notes, "people": people})
                    if "refused" in out or "malformed" in out:
                        reason = str(out.get("refused") or out.get("malformed"))
                        failed.append({"scene_id": str(sc["id"]), "label": label, "reason": reason})
                        jobs.event(job_id, JobEventType.WARNING, {"text": f"{label}: {reason}"}, agent=AGENT)
                        continue
                    scenes_port.replace_shots(UUID(str(sc["id"])), out["shots"], out["lines"], out["fields"])
                    written += 1
                    shot_count += len(out["shots"])
                    number = str(episode_no.get(str(sc["episode_id"]), 0))
                    episodes[number] = episodes.get(number, 0) + int(result.fit.get("runtime_s") or 0)
                    notes += [f"{label}: {i['message']}" for i in (result.fit.get("issues") or [])
                              if i.get("level") == "overrun"]
                    notes += [f"{label}: {i['message']}" for i in result.stored.report.get("continuity", {})
                              .get("issues") or []]
                    jobs.event(job_id, JobEventType.PROGRESS,
                               {"text": f"{label}: {len(out['shots'])} shots, {result.fit.get('runtime_s')} s",
                                "scene_id": str(sc["id"]), "shots": len(out["shots"]),
                                "total_s": result.fit.get("runtime_s"), "planner": "adam",
                                "score": (result.stored.report.get("score") or {}).get("percent")}, agent=AGENT)
        return {"written": written, "shot_count": shot_count, "failed": failed, "continuity": notes,
                "episodes": episodes, "left": [str(job["scene"]["id"]) for job in left]}

    def wrap(state: State) -> State:
        carried = state["carried"]
        failed = state["failed"]
        totals = {"scenes": state["written"] + int(carried.get("scenes", 0)),
                  "skipped": state["skipped"] + int(carried.get("skipped", 0)),
                  "shots": state["shot_count"] + int(carried.get("shots", 0)), "failed": len(failed)}
        left, notes = state["left"], state["continuity"]
        if left:
            jobs.event(job_id, JobEventType.PROGRESS, {"text": f"{len(left)} scenes left; continuing"}, agent=AGENT)
            jobs.finish(payload, totals, {"build": bool(payload.state.get("build")), "scene_ids": left,
                                          "progress": {**totals, "notes": notes[:50], "failed": failed,
                                                       "episodes": state["episodes"]}}, again=True)
            return {"result": {**totals, "continued": len(left)}}
        if failed and not totals["scenes"]:
            reason = failed[0]["reason"]
            jobs.stage(job_id, Stage.SHOTS.value, "done", "No scene could be planned with Adam")
            jobs.set(job_id, JobStatus.FAILED, error=reason if reason.startswith("Shot Planner Adam") else
                     f"{reason} Use the classic planner for these scenes.")
            return {"result": totals}
        jobs.stage(job_id, Stage.SHOTS.value, "done", f"{totals['shots']} shots in {totals['scenes']} scenes"
                   + (f"; {len(failed)} scene(s) left as they were" if failed else ""))
        by_episode: dict[str, list[str]] = {}
        for row in split.scene_status(production_id):
            by_episode.setdefault(str(row["episode_id"]), []).append(str(row["status"]))
        for episode_id, statuses in by_episode.items():
            if statuses and all(s in ("split", "approved") for s in statuses):
                split.set_episode_status(episode_id, "approved" if all(s == "approved" for s in statuses) else "ready")
        if payload.state.get("build"):
            for number in sorted(state["episodes"], key=int):
                jobs.event(job_id, JobEventType.AGENT_STEP,
                           {"text": f"Episode {int(number)}: {state['episodes'][number]} s of planned shots"},
                           agent=AGENT)
            jobs.stage(job_id, Stage.CONTINUITY.value, "active")
            for note in notes[:20]:
                jobs.event(job_id, JobEventType.WARNING, {"text": note}, agent=Agent.CONTINUITY.value)
            jobs.stage(job_id, Stage.CONTINUITY.value, "done",
                       f"{len(notes)} things to check" if notes else "No problems found")
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
    if "remove_moment" not in (payload.state.get("edit") or {}) and not llm.models_enabled():
        jobs.set(payload.job_id, JobStatus.FAILED, error=adam.NO_MODEL)
        return {"failed": adam.NO_MODEL}
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
    payload = DispatchPayload(job_id=uuid4(), kind=JobKind.PLAN_SCENE_ADAM, actor_user_id=uuid4(),
                              production_id=uuid4())
    return build(RunContext(ports=ports), payload, {"id": str(uuid4()), "settings": {}})
