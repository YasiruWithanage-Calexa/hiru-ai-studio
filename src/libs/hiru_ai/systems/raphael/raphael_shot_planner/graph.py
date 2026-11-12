"""raphael_shot_planner: scenes -> clips -> `shots` rows. The last hop of the structure build when the production's
`shot_planner` setting says `raphael`, and the director's "Plan with Raphael" / "More cinematic" (plan/2026-11-08e).

    load   the scenes to plan (approved ones and ones with no script are skipped)
    plan   every scene at once in a rolling pool (`RAPHAEL_WORKERS`); a scene is two stages (the must bin, then the
           cinematic pass) under one run cap. Each scene is written (in this thread) as it finishes. Past the time
           budget
           no new scene starts and the rest go to a fresh delivery of this hop, so nothing is held in memory between
           deliveries.
    wrap   totals, then the next delivery, or the episodes' status and the build log

A scene whose input (script, lines, cast, reading, length cap) is unchanged since Raphael planned it is kept as it is,
with no
call, unless the delivery says `replan`. A delivery can carry an EDIT for scenes: `{"cap": 2.5}` plans with that
length cap
(the person's choice for this run, else the production's `raphael_length_cap`), `{"note": "..."}` puts a person's note
in the
scene's context, `{"stage": "cinematic"}` runs stage 2 alone over the stored must bin ("More cinematic"). Idempotent: a
scene's shots are replaced, never appended. With no model the job fails clearly and says to use the classic planner.
"""

from __future__ import annotations

import contextvars
import logging
import queue
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from typing import Any
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from contracts import sceneplan
from contracts.build import Agent, Stage
from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from contracts.production import ProductionSettings
from contracts.raphael import state as ledger_state
from contracts.raphael.stored import StoredRaphael
from contracts.reading import SceneReading
from contracts.stagemap import SceneStaging
from hiru_ai.core import agents, llm, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.registry import Registry
from hiru_ai.core.settings import get_settings
from hiru_ai.systems.raphael.raphael_shot_planner import scene as raphael
from hiru_ai.systems.raphael.raphael_shot_planner.state import State

_log = logging.getLogger(__name__)
AGENT = Agent.PLANNER.value
# No new scene starts after this many seconds of the 1800 s deadline: a scene is two conversations of several minutes
# each,
# so one that starts last still has 900 s.
TIME_BUDGET_S = 900.0
Row = dict[str, Any]


def previous_of(shots: list[Row], stored: StoredRaphael | None) -> Row:
    """The shot list to keep for a side-by-side look: what the scene had before Raphael first planned it."""
    if stored is not None and stored.previous:
        return stored.previous
    others = [s for s in shots if s.get("planner", "classic") != "raphael"]
    keys = (
        "number",
        "title",
        "framing",
        "duration_s",
        "sound_mode",
        "camera_link",
        "block_start",
        "block_end",
        "words",
    )
    return (
        {
            "planner": others[0].get("planner", "classic") if others else "classic",
            "shots": [{k: s.get(k) for k in keys} for s in others],
        }
        if others
        else {}
    )


def build(
    ctx: RunContext, payload: DispatchPayload, production: Row, *, budget_s: float | None = None
) -> CompiledStateGraph[Any, Any, Any, Any]:
    jobs, scenes_port, split = ctx.need("jobs"), ctx.need("scenes"), ctx.need("split")
    job_id, production_id = payload.job_id, payload.production_id
    assert production_id is not None
    write = parts.step("raphael_write", "step")
    prep = parts.step("scene_prep")  # the stager's map, kept or made the way every planner keeps it (plan/2026-11-09)
    started = time.monotonic()
    limit = TIME_BUDGET_S if budget_s is None else budget_s
    edit: Row = dict(payload.state.get("edit") or {})
    replan = bool(payload.state.get("replan"))
    settings = ProductionSettings.model_validate(production.get("settings") or {})
    # the length cap: this run's choice, else the production's (plan §2.1, L2)
    cap = raphael.a_cap(edit.get("cap") or payload.state.get("cap"), raphael.a_cap(settings.raphael_length_cap))
    cinematic_only = payload.kind.value == "cinematic_scene_raphael" or edit.get("stage") == "cinematic"
    use_packet = get_settings().raphael_packet  # plan/2026-11-11 phase 4 (off until the live check)

    characters = split.characters(production_id)
    canon = scenes_port.canon(production_id)
    episode_rows = {str(e["id"]): e for e in split.episodes(production_id)}
    episode_no = {k: int(e["number"]) for k, e in episode_rows.items()}
    locations = {str(r["id"]): r for r in split.locations(production_id)}
    props = [c for c in canon if c.get("kind") == "prop"]
    everything = sorted(
        scenes_port.scenes(production_id, None),
        key=lambda r: (episode_no.get(str(r["episode_id"]), 0), int(r.get("number") or 0)),
    )
    by_id = {str(r["id"]): r for r in everything}
    position = {str(r["id"]): n for n, r in enumerate(everything)}
    persona = None
    producer = getattr(ctx.ports, "producer", None)
    if producer is not None:
        try:
            persona = producer.lead_persona(production_id)
        except Exception:  # a persona is a nicety: no persona, no style note
            persona = None

    def neighbour(sid: str, step: int) -> Row | None:
        """The scene before (-1) or after (+1) this one in the same episode."""
        n = position[sid] + step
        other = everything[n] if 0 <= n < len(everything) else None
        return other if other and str(other["episode_id"]) == str(by_id[sid]["episode_id"]) else None

    def stored_row(row: Row | None) -> StoredRaphael | None:
        return StoredRaphael.load((row or {}).get("raphael"))

    cards = {str(c["name"]): (c.get("current") or {}) for c in characters}
    production_pack = {
        "style_note": str((persona or {}).get("style_note") or production.get("style_note") or ""),
        "rules": ([f"Never name or show: {', '.join(settings.banned_terms)}"] if settings.banned_terms else []),
        "people": [
            {
                "name": str(c["name"]),
                "code": str(c.get("code") or ""),
                "look": str(
                    cards[str(c["name"])].get("wardrobe_anchor")
                    or (cards[str(c["name"])].get("card") or {}).get("appearance")
                    or ""
                ),
                "voice": str(cards[str(c["name"])].get("voice_pin") or ""),
                # who they are (the canon card's summary): the coverage is planned from it
                "essence": str((cards[str(c["name"])].get("card") or {}).get("summary") or ""),
            }
            for c in characters
        ],
    }

    def gist(row: Row | None) -> str:
        return " — ".join(p for p in (str((row or {}).get("heading") or ""), str((row or {}).get("title") or "")) if p)

    names = {str(c["id"]): str(c["name"]) for c in characters}
    codes = {str(c.get("code") or ""): str(c["name"]) for c in characters if c.get("code")}
    place_notes = prep.location_notes(list(locations.values()))

    # ── the scene's state ledger (plan/2026-11-09 phase 3) ─────────────────────────────────────

    def ledger_of(
        sc: Row, lines: list[Row], cast: list[str], reading: SceneReading | None, scene_ctx: RunContext
    ) -> tuple[raphael.Ledger, Any]:
        """-> (the scene's map, the items it is for). A current stored map or a person's map costs nothing; else ONE
        stager call (no implied walks for Raphael, D3). A stager failure is not a Raphael failure: the scene is
        planned without a map, and the job says so."""
        items = sceneplan.items_for(sc.get("script") or [], lines)
        place = place_notes.get(str(sc.get("location_id")), "")

        def ask(its: list[Any]) -> Row:
            out = agents.build("stager").run(
                {
                    "items": its,
                    "speaker_names": names,
                    "reading_text": reading.text() if reading else "",
                    "place": place,
                },
                scene_ctx,
            )
            return dict(out.model_dump(mode="json"))

        staging: SceneStaging | None
        try:
            staging, made = prep.staging_for(sc, items, ask, cast)
        except Exception:  # a broken map is not a broken scene
            _log.warning("the state map failed for scene %s", sc.get("id"), exc_info=True)
            staging, made = None, False
        if staging is None:
            return raphael.Ledger(note="No state map for this scene; planned without it"), items
        return raphael.Ledger(staging=staging, made=made), items

    # ── planning one scene (in a worker; the writing happens in the main thread) ───────────────

    moods: dict[str, tuple[str, ...]] = {}  # scene id -> the packet's mood words (plan/2026-11-12b D7)

    def packet_of(sc: Row, lines: list[Row], scene_ctx: RunContext) -> tuple[str, Any, dict[str, str]] | None:
        """plan/2026-11-11 phase 4: the scene's stored packet when `RAPHAEL_PACKET` is on and the scene has a complete,
        current one (the stager runs first if the scene has no map). Otherwise None, and the job says why."""
        if not use_packet:
            return None
        try:
            got, why = parts.module("system", "breakdown_build", "graph").packet_for(scene_ctx, sc)
        except Exception:  # no breakdown part, or a broken store: today's path
            _log.warning("the scene packet could not be read for %s", sc.get("id"), exc_info=True)
            got, why = None, "the breakdown could not be read"
        made = raphael.from_packet(got, lines) if got is not None else None
        if made is not None:  # plan/2026-11-12b D7: the packet's mood words travel with the plan to the first frame
            feeling = got.get("F_feeling") if isinstance(got.get("F_feeling"), dict) else {}
            moods[str(sc["id"])] = tuple(str(m) for m in feeling.get("mood") or [] if isinstance(m, str))
        if made is None:
            why = why or "the packet's spoken lines do not match the scene's lines"
            jobs.event(job_id, JobEventType.PROGRESS,
                       {"text": f"{label_of(sc)}: planned from the script, not the scene packet ({why})."}, agent=AGENT)
        return made

    def plan_one(job: Row) -> raphael.Planned | raphael.Unchanged | str:
        sc, lines = job["scene"], job["lines"]
        sid = str(sc["id"])
        stored = stored_row(sc)
        from_packet = packet_of(sc, lines, replace(ctx, scene_id=UUID(sid)))
        bare, _ = raphael.script_of(sc, lines, cast=[], others=[], place="", objects=[])
        cast = raphael.present(characters, bare.blocks)
        location = locations.get(str(sc.get("location_id")))
        place = str((location or {}).get("name") or sc.get("heading") or "")
        script, line_ids = raphael.script_of(
            sc,
            lines,
            cast=cast,
            others=raphael.others_of(characters, cast),
            place=place,
            objects=raphael.objects_of(props, location, bare.blocks),
        )
        episode = episode_rows.get(str(sc.get("episode_id"))) or {}
        reading = SceneReading.of(sc)
        # The scene's id on every usage row of its calls (plan/2026-11-08f §6; written once `usage_scene` is on).
        scene_ctx = replace(ctx, scene_id=UUID(sid))
        if from_packet is not None:  # the packet carries the state ledger already (its `stage`): no stager call here
            opening, script, line_ids = from_packet
            ledger = raphael.Ledger(note="")
        else:
            opening = ""
            ledger, items = (
                ledger_of(sc, lines, cast, reading, scene_ctx)
                if not cinematic_only
                else (raphael.Ledger(staging=SceneStaging.of(sc)), sceneplan.items_for(sc.get("script") or [], lines))
            )
            script = ledger_state.attach(script, ledger.staging, items, codes)
        note = " ".join(p for p in (str(sc.get("note") or ""), str(edit.get("note") or "")) if p)
        context = {
            "heading": str(sc.get("heading") or ""),
            "note": note,
            "episode_title": str(episode.get("title") or ""),
            "synopsis": str(episode.get("synopsis") or ""),
            "before": gist(neighbour(sid, -1)),
            "after": gist(neighbour(sid, 1)),
            "place": str((((location or {}).get("current") or {}).get("card") or {}).get("look") or ""),
        }
        planner = raphael.Planner(
            scene_ctx,
            script,
            number=int(sc.get("number") or 0),
            line_ids=line_ids,
            production=production_pack,
            context=context,
            cap=cap,
            extra=(
                "The scene's reading (a person's; keep it):\n" + reading.text()
                if reading is not None and reading.by == "person"
                else ""
            ),
            opening=opening,
            mood=moods.get(sid, ()) if from_packet is not None else (),
        )
        try:
            shots = scenes_port.shots(UUID(sid))
            previous = previous_of(shots, stored)
            if cinematic_only:
                if stored is None:
                    return "This scene was not planned by Raphael, so there is no must bin to add to. Plan it first."
                done = planner.more_cinematic(stored, previous=previous, job_id=str(job_id))
                done.ledger = ledger
                return done
            same = stored is not None and stored.input_hash == planner.input_hash()
            if (
                stored is not None
                and same
                and not edit
                and not replan
                and any(s.get("planner") == "raphael" for s in shots)
            ):
                return raphael.Unchanged(stored, ledger)  # same input, the result a person already saw
            done = planner.plan(
                previous=previous,
                job_id=str(job_id),
                reuse=stored.breakdown if stored is not None and same else None,  # same input: the same breakdown
            )
            done.ledger = ledger
            return done
        except raphael.Failed as failure:
            return str(failure)

    def label_of(sc: Row) -> str:
        return f"Ep {episode_no.get(str(sc['episode_id']), 0):02d} Scene {sc['number']}"

    # ── the graph ──────────────────────────────────────────────────────────────────────────────

    def load(state: State) -> State:
        carried: Row = dict(payload.state.get("progress") or {})
        scene_ids = payload.state.get("scene_ids")
        wanted = {str(s) for s in scene_ids} if scene_ids is not None else None
        rows = [r for r in everything if wanted is None or str(r["id"]) in wanted]
        if not carried:
            jobs.stage(job_id, Stage.SHOTS.value, "active", f"Planning shots for {len(rows)} scenes with Raphael")
        todo: list[Row] = []
        skipped = 0
        for sc in rows:
            label = label_of(sc)
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
        written = shot_count = reused = 0
        planned_ids: list[str] = []

        def write_result(job: Row, result: raphael.Planned | raphael.Unchanged | str) -> None:
            nonlocal written, shot_count, reused
            sc, label = job["scene"], job["label"]
            if isinstance(result, str):
                failed.append({"scene_id": str(sc["id"]), "label": label, "reason": result})
                jobs.event(job_id, JobEventType.WARNING, {"text": f"{label}: {result}"}, agent=AGENT)
                return
            for warning in getattr(result, "warnings", []):  # plan/2026-11-10: a breakdown that could not be made
                jobs.event(job_id, JobEventType.WARNING, {"text": f"{label}: {warning}"}, agent=AGENT)
            if result.ledger.note:
                jobs.event(job_id, JobEventType.WARNING, {"text": f"{label}: {result.ledger.note}"}, agent=AGENT)
            made = result.ledger.staging is not None and result.ledger.made
            if made and result.ledger.staging is not None:  # the map the stager just made goes with the shots
                sc["staging"] = result.ledger.staging.model_dump(mode="json")
            if isinstance(result, raphael.Unchanged):
                if made:
                    # no shot changes: the map alone (save_plan with no shots is the scene's own fields)
                    scenes_port.save_plan(UUID(str(sc["id"])), [], [], [], {"staging": sc["staging"]})
                reused += 1
                jobs.event(
                    job_id,
                    JobEventType.PROGRESS,
                    {"text": f"{label}: nothing has changed since Raphael planned it; left as it is"},
                    agent=AGENT,
                )
                return
            out = write.run(
                {
                    "scene": sc,
                    "lines": job["lines"],
                    "stored": result.stored.data(),
                    "canon": canon,
                    "production": production,
                    "job_id": str(job_id),
                }
            )
            if "refused" in out or "malformed" in out:
                reason = str(out.get("refused") or out.get("malformed"))
                failed.append({"scene_id": str(sc["id"]), "label": label, "reason": reason})
                jobs.event(job_id, JobEventType.WARNING, {"text": f"{label}: {reason}"}, agent=AGENT)
                return
            fields = {**out["fields"], **({"staging": sc["staging"]} if made else {})}
            scenes_port.replace_shots(UUID(str(sc["id"])), out["shots"], out["lines"], fields)
            out["fields"] = fields
            sc.update(out["fields"])
            by_id[str(sc["id"])].update(out["fields"])
            written += 1
            planned_ids.append(str(sc["id"]))
            shot_count += len(out["shots"])
            report = out["fields"]["fit_report"]
            number = str(episode_no.get(str(sc["episode_id"]), 0))
            episodes[number] = episodes.get(number, 0) + int(report.get("total_s") or 0)
            stored = result.stored
            if stored.stopped:
                notes.append(f"{label}: {stored.stopped}")
            notes.extend(
                f"{label}: {item.sentence}" for item in stored.left if item.fix == "report" and item.code == "clock"
            )
            jobs.event(
                job_id,
                JobEventType.PROGRESS,
                {
                    "text": f"{label}: {len(out['shots'])} clips, {report.get('total_s')} s",
                    "scene_id": str(sc["id"]),
                    "shots": len(out["shots"]),
                    "total_s": report.get("total_s"),
                    "planner": "raphael",
                    "cinematic": len(stored.extras()),
                    "left": len(stored.left),
                },
                agent=AGENT,
            )

        results: queue.Queue[tuple[Row, raphael.Planned | raphael.Unchanged | str]] = queue.Queue()
        first = [True]

        def run_one(job: Row) -> Row | None:
            """One scene; -> the scene when the time budget kept it from starting (a later delivery plans it)."""
            if not first[0] and time.monotonic() - started > limit:
                return job
            first[0] = False
            results.put((job, plan_one(job)))
            return None

        workers = max(1, get_settings().raphael_workers)
        pending: list[Future[Row | None]] = []
        left_jobs: list[Row] = []
        with ThreadPoolExecutor(max_workers=min(workers, max(1, len(todo)))) as pool:
            for job in todo:  # copied here, in this thread, one per task
                pending.append(pool.submit(contextvars.copy_context().run, run_one, job))
            while pending or not results.empty():
                try:
                    job, result = results.get(timeout=0.1)
                except queue.Empty:
                    for f in [f for f in pending if f.done()]:
                        pending.remove(f)
                        kept = f.result()
                        if kept is not None:
                            left_jobs.append(kept)
                    continue
                write_result(job, result)
        return {
            "written": written,
            "shot_count": shot_count,
            "failed": failed,
            "continuity": notes,
            "reused": reused,
            "episodes": episodes,
            "left": [str(job["scene"]["id"]) for job in left_jobs],
            "planned": planned_ids,
        }

    def wrap(state: State) -> State:
        carried = state["carried"]
        failed = state["failed"]
        totals = {
            "scenes": state["written"] + int(carried.get("scenes", 0)),
            "skipped": state["skipped"] + state["reused"] + int(carried.get("skipped", 0)),
            "shots": state["shot_count"] + int(carried.get("shots", 0)),
            "failed": len(failed),
        }
        left = state["left"]
        notes = list(state["continuity"])
        if left:
            jobs.event(job_id, JobEventType.PROGRESS, {"text": f"{len(left)} scenes left; continuing"}, agent=AGENT)
            # the request's own choices go on with it: a fresh delivery must plan the way this one was asked to
            jobs.finish(
                payload,
                totals,
                {
                    "build": bool(payload.state.get("build")),
                    "scene_ids": left,
                    "replan": replan,
                    "edit": edit,
                    "cap": cap,
                    "progress": {**totals, "notes": notes[:50], "failed": failed, "episodes": state["episodes"]},
                },
                again=True,
            )
            return {"result": {**totals, "continued": len(left)}}
        if failed and not totals["scenes"]:
            reason = failed[0]["reason"]
            jobs.stage(job_id, Stage.SHOTS.value, "done", "No scene could be planned with Raphael")
            jobs.set(
                job_id,
                JobStatus.FAILED,
                error=reason
                if reason.startswith("Shot Planner Raphael")
                else f"{reason} Use the classic planner for these scenes.",
            )
            return {"result": totals}
        jobs.stage(
            job_id,
            Stage.SHOTS.value,
            "done",
            f"{totals['shots']} clips in {totals['scenes']} scenes"
            + (f"; {len(failed)} scene(s) left as they were" if failed else ""),
        )
        by_episode: dict[str, list[str]] = {}
        for row in split.scene_status(production_id):
            by_episode.setdefault(str(row["episode_id"]), []).append(str(row["status"]))
        for episode_id, statuses in by_episode.items():
            if statuses and all(s in ("split", "approved") for s in statuses):
                split.set_episode_status(episode_id, "approved" if all(s == "approved" for s in statuses) else "ready")
        if payload.state.get("build"):
            for number in sorted(state["episodes"], key=int):
                jobs.event(
                    job_id,
                    JobEventType.AGENT_STEP,
                    {"text": f"Episode {int(number)}: {state['episodes'][number]} s of planned takes"},
                    agent=AGENT,
                )
            jobs.stage(job_id, Stage.CONTINUITY.value, "active")
            for note in notes[:20]:
                jobs.event(job_id, JobEventType.WARNING, {"text": note}, agent=Agent.CONTINUITY.value)
            jobs.stage(
                job_id,
                Stage.CONTINUITY.value,
                "done",
                f"{len(notes)} things to check" if notes else "No problems found",
            )
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
    if not llm.models_enabled():
        jobs.set(payload.job_id, JobStatus.FAILED, error=raphael.NO_MODEL)
        return {"failed": raphael.NO_MODEL}
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
    payload = DispatchPayload(
        job_id=uuid4(), kind=JobKind.PLAN_SCENE_RAPHAEL, actor_user_id=uuid4(), production_id=uuid4()
    )
    return build(RunContext(ports=ports), payload, {"id": str(uuid4()), "settings": {}})
