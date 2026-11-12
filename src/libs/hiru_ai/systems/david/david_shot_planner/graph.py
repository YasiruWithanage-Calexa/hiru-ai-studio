"""david_shot_planner: scenes -> shots -> `shots` rows. The last hop of the structure build when the production's
`shot_planner` setting says `david`, and the director's "Plan with David" (plan/2026-11-05e §4.4).

    load   the scenes to plan (approved ones and ones with no script are skipped) and how each one follows the one
    before
    plan   chains of scenes: scenes that carry on from the one before run in order inside one worker, each fed the end
           state and the last shot of the one before; every other chain runs at once in a rolling pool
           (`DAVID_WORKERS`). Each scene is written (in this thread) as it finishes. Past the time budget no new scene
           starts and the rest go to a fresh delivery of this hop, which carries on from the end state stored in
           `scenes.david`, so nothing is held in memory between deliveries.
    wrap   totals, the joins with approved scenes, then the next delivery, or the episodes' status and the build log

A scene whose input (script, lines, cast, start state, removed additions) is unchanged since David planned it is kept as
it is, with no call, unless the delivery says `replan`. A replan in the middle of a chain changes that scene's end
state;
the scenes after it that David has planned are then replanned in order only until one's end state comes out the same as
before, and an approved scene stops it (its join is reported). A delivery can carry an EDIT for one scene
(`state.edit`): `{"note": "..."}` makes one repair call with the person's note, `{"remove_added": n}` takes an addition
out with no model. Idempotent: a scene's shots are replaced, never appended. With no model the job fails clearly and
says
to use the classic planner: David has no rules fallback worth having.
"""
from __future__ import annotations

import contextvars
import logging
import queue
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from contracts import sceneplan
from contracts.build import Agent, Stage
from contracts.david.stored import Link, StoredPlan
from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from contracts.production import ProductionSettings
from contracts.reading import SceneReading
from hiru_ai.core import llm, packets, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.registry import Registry
from hiru_ai.core.settings import get_settings
from hiru_ai.systems.david.david_shot_planner import scene as david
from hiru_ai.systems.david.david_shot_planner.state import State

_log = logging.getLogger(__name__)
AGENT = Agent.PLANNER.value
# No new scene starts after this many seconds of the 1800 s deadline (plan §4.4): a scene is one call of 3 to 6 minutes
# and at most two repairs, so one that starts last still has 900 s.
TIME_BUDGET_S = 900.0
Row = dict[str, Any]


def previous_of(shots: list[Row], stored: StoredPlan | None) -> Row:
    """The shot list to keep for a side-by-side look: what the scene had before David first planned it."""
    if stored is not None and stored.previous:
        return stored.previous
    others = [s for s in shots if s.get("planner", "classic") != "david"]
    keys = ("number", "title", "framing", "duration_s", "sound_mode", "camera_link", "block_start", "block_end",
            "words")
    return {"planner": others[0].get("planner", "classic") if others else "classic",
            "shots": [{k: s.get(k) for k in keys} for s in others]} if others else {}


def build(ctx: RunContext, payload: DispatchPayload, production: Row, *,
          budget_s: float | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    jobs, scenes_port, split = ctx.need("jobs"), ctx.need("scenes"), ctx.need("split")
    job_id, production_id = payload.job_id, payload.production_id
    assert production_id is not None
    write = parts.step("david_write", "step")
    started = time.monotonic()
    limit = TIME_BUDGET_S if budget_s is None else budget_s
    edit: Row = dict(payload.state.get("edit") or {})
    replan = bool(payload.state.get("replan"))
    settings = ProductionSettings.model_validate(production.get("settings") or {})
    order = str(payload.state.get("order") or settings.david_order)

    characters = split.characters(production_id)
    canon = scenes_port.canon(production_id)
    episode_rows = {str(e["id"]): e for e in split.episodes(production_id)}
    episode_no = {k: int(e["number"]) for k, e in episode_rows.items()}
    locations = {str(r["id"]): r for r in split.locations(production_id)}
    props = [c for c in canon if c.get("kind") == "prop"]
    everything = sorted(scenes_port.scenes(production_id, None),
                        key=lambda r: (episode_no.get(str(r["episode_id"]), 0), int(r.get("number") or 0)))
    by_id = {str(r["id"]): r for r in everything}
    position = {str(r["id"]): n for n, r in enumerate(everything)}
    persona = None
    producer = getattr(ctx.ports, "producer", None)
    if producer is not None:
        try:
            persona = producer.lead_persona(production_id)
        except Exception:  # a persona is a nicety: no persona, no style note
            persona = None

    def before_of(sid: str) -> Row | None:
        """The scene before this one in the same episode."""
        n = position[sid] - 1
        prev = everything[n] if n >= 0 else None
        return prev if prev and str(prev["episode_id"]) == str(by_id[sid]["episode_id"]) else None

    def after_of(sid: str) -> Row | None:
        n = position[sid] + 1
        nxt = everything[n] if n < len(everything) else None
        return nxt if nxt and str(nxt["episode_id"]) == str(by_id[sid]["episode_id"]) else None

    def stored_row(row: Row | None) -> StoredPlan | None:
        return StoredPlan.load((row or {}).get("david"))

    # how each scene follows the one before: the rule, a person's choice on top (plan §4.3)
    overrides: dict[str, str] = {}
    for row in everything:
        kept = stored_row(row)
        if kept is not None and kept.link.by == "person":
            overrides[str(row["id"])] = kept.link.kind or "none"
    made = parts.step("david_links", "step").run({
        "scenes": [{**r, "episode_number": episode_no.get(str(r["episode_id"]), 0)} for r in everything],
        "order": order, "overrides": overrides})
    links: dict[str, str] = dict(made["links"])

    cards = {str(c["name"]): (c.get("current") or {}) for c in characters}
    production_pack = {
        "style_note": str((persona or {}).get("style_note") or production.get("style_note") or ""),
        "rules": ([f"Never name or show: {', '.join(settings.banned_terms)}"] if settings.banned_terms else []),
        "people": [{"name": str(c["name"]), "code": str(c.get("code") or ""),
                   "look": str(cards[str(c["name"])].get("wardrobe_anchor") or
                               (cards[str(c["name"])].get("card") or {}).get("appearance") or ""),
                   "voice": str(cards[str(c["name"])].get("voice_pin") or "")} for c in characters]}

    def gist(row: Row | None) -> str:
        return " — ".join(p for p in (str((row or {}).get("heading") or ""), str((row or {}).get("title") or "")) if p)

    def chain_back(sid: str) -> list[StoredPlan]:
        """Stored plans of the scenes before this one that it carries on from, nearest first."""
        out: list[StoredPlan] = []
        while links.get(sid):
            prev = before_of(sid)
            kept = stored_row(prev)
            if prev is None or kept is None:
                break
            out.append(kept)
            sid = str(prev["id"])
        return out

    # ── planning one scene (in a worker; the writing happens in the main thread) ───────────────

    def plan_one(job: Row, fresh: dict[str, StoredPlan]) -> david.Planned | david.Unchanged | str:
        sc, lines = job["scene"], job["lines"]
        sid = str(sc["id"])
        stored = stored_row(sc)
        bare, _ = david.script_of(sc, lines, cast=[], others=[], place="", objects=[])
        cast = david.present(characters, bare.blocks)
        location = locations.get(str(sc.get("location_id")))
        place = str((location or {}).get("name") or sc.get("heading") or "")
        script, line_ids = david.script_of(sc, lines, cast=cast, others=david.others_of(characters, cast), place=place,
                                           objects=david.objects_of(props, location, bare.blocks,
                                                                    packets.canon_things(ctx, sc)))
        kind = links.get(sid, "")
        prev = before_of(sid)
        before_stored = fresh.get(str(prev["id"])) if prev else None
        before_stored = before_stored or stored_row(prev)
        before = before_stored.end_state if before_stored else None
        start = before if kind and before is not None else None
        # the scene before's last shot, word for word (D8), and every look change recorded earlier in the chain (D9)
        last_ir = before_stored.plan.shots[-1].ir if kind and before_stored and before_stored.plan.shots else None
        earlier = [c.model_dump() for p in reversed(chain_back(sid)) for c in p.look_changes]
        episode = episode_rows.get(str(sc.get("episode_id"))) or {}
        reading = SceneReading.of(sc)
        context = {"heading": str(sc.get("heading") or ""), "note": str(sc.get("note") or ""),
                   "episode_title": str(episode.get("title") or ""), "synopsis": str(episode.get("synopsis") or ""),
                   "before": gist(prev), "after": gist(after_of(sid)),
                   "place": str((((location or {}).get("current") or {}).get("card") or {}).get("look") or "")}
        pack = {"production": production_pack, "context": context,
                "canon_looks": {n: str(cards[n].get("wardrobe_anchor") or (cards[n].get("card") or {})
                                       .get("appearance") or "") for n in cast if n in cards},
                "look_changes": earlier, "last_shot_ir": last_ir,
                "reading": reading.text() if reading is not None and reading.by == "person" else ""}
        link = Link(kind=kind or "", by="person" if sid in overrides else "rules")  # type: ignore[arg-type]
        planner = david.Planner(ctx, script, number=int(sc.get("number") or 0), line_ids=line_ids, pack=pack,
                                removed=list(stored.removed) if stored else [], link=link, start=start, before=before)
        try:
            shots = scenes_port.shots(UUID(sid))
            previous = previous_of(shots, stored)
            if "remove_added" in edit:
                if stored is None:
                    return "This scene was not planned by David, so there is nothing to remove from."
                return planner.remove_added(stored, int(edit["remove_added"]), job_id=str(job_id))
            same = stored is not None and stored.input_hash == planner.input_hash()
            if same and not edit and not replan and any(s.get("planner") == "david" for s in shots):
                return david.Unchanged(stored)  # type: ignore[arg-type]  # same input, the plan a person already saw
            if "note" in edit:
                if stored is None:
                    return "This scene was not planned by David, so there is no plan to change."
                return planner.with_note(stored, str(edit["note"]), previous=previous, job_id=str(job_id),
                                         before_end=stored.end_state)
            return planner.plan(previous=previous, job_id=str(job_id),
                                before_end=stored.end_state if stored else None)
        except david.Failed as failure:
            return str(failure)

    def chain_of(job: Row, done: dict[str, StoredPlan]) -> Row | None:
        """The scene that must be planned again because this one's end state changed: the next scene of the episode,
        when
        it carries on from this one, David has planned it and nobody approved it."""
        nxt = after_of(str(job["scene"]["id"]))
        if nxt is None or not links.get(str(nxt["id"])) or nxt["status"] == "approved":
            return None
        if stored_row(nxt) is None:
            return None
        lines = scenes_port.lines(UUID(str(nxt["id"])))
        if not sceneplan.items_for(nxt.get("script") or [], lines):
            return None
        return {"label": label_of(nxt), "scene": nxt, "lines": lines}

    def label_of(sc: Row) -> str:
        return f"Ep {episode_no.get(str(sc['episode_id']), 0):02d} Scene {sc['number']}"

    # ── the graph ──────────────────────────────────────────────────────────────────────────────

    def load(state: State) -> State:
        carried: Row = dict(payload.state.get("progress") or {})
        scene_ids = payload.state.get("scene_ids")
        wanted = {str(s) for s in scene_ids} if scene_ids is not None else None
        rows = [r for r in everything if wanted is None or str(r["id"]) in wanted]
        if not carried:
            jobs.stage(job_id, Stage.SHOTS.value, "active", f"Planning shots for {len(rows)} scenes with David")
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

    def chains_of(todo: list[Row]) -> list[list[Row]]:
        """The scenes to plan in the order they run: a scene that carries on from the one just before it joins that
        scene's chain; every other scene starts a chain of its own (they run at once)."""
        out: list[list[Row]] = []
        for job in todo:
            sid = str(job["scene"]["id"])
            prev = before_of(sid)
            if out and links.get(sid) and prev is not None and str(out[-1][-1]["scene"]["id"]) == str(prev["id"]):
                out[-1].append(job)
            else:
                out.append([job])
        return out

    def plan(state: State) -> State:
        todo, carried = state["todo"], state["carried"]
        notes: list[str] = list(carried.get("notes") or [])
        failed: list[Row] = list(carried.get("failed") or [])
        episodes: dict[str, int] = {k: int(v) for k, v in (carried.get("episodes") or {}).items()}
        written = shot_count = reused = 0
        planned_ids: list[str] = []

        def write_result(job: Row, result: david.Planned | david.Unchanged | str) -> None:
            nonlocal written, shot_count, reused
            sc, label = job["scene"], job["label"]
            if isinstance(result, str):
                failed.append({"scene_id": str(sc["id"]), "label": label, "reason": result})
                jobs.event(job_id, JobEventType.WARNING, {"text": f"{label}: {result}"}, agent=AGENT)
                return
            if isinstance(result, david.Unchanged):
                reused += 1
                jobs.event(job_id, JobEventType.PROGRESS,
                           {"text": f"{label}: nothing has changed since David planned it; left as it is"}, agent=AGENT)
                return
            out = write.run({"scene": sc, "lines": job["lines"], "stored": result.stored.data(), "canon": canon,
                             "production": production, "job_id": str(job_id)})
            if "refused" in out or "malformed" in out:
                reason = str(out.get("refused") or out.get("malformed"))
                failed.append({"scene_id": str(sc["id"]), "label": label, "reason": reason})
                jobs.event(job_id, JobEventType.WARNING, {"text": f"{label}: {reason}"}, agent=AGENT)
                return
            scenes_port.replace_shots(UUID(str(sc["id"])), out["shots"], out["lines"], out["fields"])
            sc.update(out["fields"])  # a later scene of this delivery reads this one's stored plan
            by_id[str(sc["id"])].update(out["fields"])
            written += 1
            planned_ids.append(str(sc["id"]))
            shot_count += len(out["shots"])
            report = out["fields"]["fit_report"]
            number = str(episode_no.get(str(sc["episode_id"]), 0))
            episodes[number] = episodes.get(number, 0) + int(report.get("total_s") or 0)
            stored = result.stored
            notes.extend(f"{label}: {p.sentence}" for p in stored.problems if p.fix == "report"
                         and p.code in ("clock", "envelope"))
            notes.extend(f"{label}: {p.sentence}" for p in stored.seams)
            if stored.look_changes:
                notes.extend(f"{label}: {c.who} changes from \"{c.before}\" to \"{c.after}\""
                             for c in stored.look_changes)
            jobs.event(job_id, JobEventType.PROGRESS,
                       {"text": f"{label}: {len(out['shots'])} shots, {report.get('total_s')} s",
                        "scene_id": str(sc["id"]), "shots": len(out["shots"]), "total_s": report.get("total_s"),
                        "planner": "david", "calls": stored.report.get("calls"), "left": len(stored.problems)},
                       agent=AGENT)

        results: queue.Queue[tuple[Row, david.Planned | david.Unchanged | str]] = queue.Queue()
        first = [True]

        def run_chain(chain: list[Row]) -> list[Row]:
            """One chain, in order. A scene's stored plan is written before the next one starts (the main thread
            writes as
            results arrive), so a chain cut by the budget carries on from the database. -> the scenes not started."""
            fresh: dict[str, StoredPlan] = {}
            left: list[Row] = []
            queue_ = list(chain)
            i = 0
            while i < len(queue_):
                job = queue_[i]
                i += 1
                if not first[0] and time.monotonic() - started > limit:
                    left = queue_[i - 1:]
                    break
                first[0] = False
                result = plan_one(job, fresh)
                results.put((job, result))
                if isinstance(result, david.Planned):
                    fresh[str(job["scene"]["id"])] = result.stored
                    if i == len(queue_) and result.changed_end:  # the scenes after it may be out of date (§4.4)
                        extra = chain_of(job, fresh)
                        if extra is not None:
                            queue_.append(extra)
                elif isinstance(result, david.Unchanged):
                    fresh[str(job["scene"]["id"])] = result.stored
            return left

        workers = max(1, get_settings().david_workers)
        chains = chains_of(todo)
        pending: list[Future[list[Row]]] = []
        left_jobs: list[Row] = []
        with ThreadPoolExecutor(max_workers=min(workers, max(1, len(chains)))) as pool:
            for chain in chains:  # copied here, in this thread, one per task
                pending.append(pool.submit(contextvars.copy_context().run, run_chain, chain))
            while pending or not results.empty():
                try:
                    job, result = results.get(timeout=0.1)
                except queue.Empty:
                    for f in [f for f in pending if f.done()]:
                        pending.remove(f)
                        left_jobs += f.result()
                    continue
                write_result(job, result)
        left = left_jobs
        return {"written": written, "shot_count": shot_count, "failed": failed, "continuity": notes, "reused": reused,
                "episodes": episodes, "left": [str(job["scene"]["id"]) for job in left], "planned": planned_ids}

    def joins(planned: list[str]) -> list[str]:
        """The join between a scene planned in this job and the scene after it when that one is already planned (an
        approved scene is never replanned, so its join is only reported)."""
        out = []
        seams = parts.step("david_seams", "step")
        for sid in planned:
            nxt = after_of(sid)
            here, there = stored_row(by_id[sid]), stored_row(nxt)
            if nxt is None or here is None or there is None or here.end_state is None:
                continue
            found = seams.run({"before": here.end_state.model_dump(mode="json"), "link": links.get(str(nxt["id"]), ""),
                               "start": there.start.model_dump(mode="json") if there.start else None,
                               "after": there.plan.model_dump(mode="json"), "number": int(nxt.get("number") or 0)})
            tag = "approved" if nxt["status"] == "approved" else "planned"
            out += [f"{label_of(nxt)} ({tag}): {p['sentence']}" for p in found.get("problems") or []]
        return out

    def wrap(state: State) -> State:
        carried = state["carried"]
        failed = state["failed"]
        totals = {"scenes": state["written"] + int(carried.get("scenes", 0)),
                  "skipped": state["skipped"] + state["reused"] + int(carried.get("skipped", 0)),
                  "shots": state["shot_count"] + int(carried.get("shots", 0)), "failed": len(failed)}
        left = state["left"]
        notes = [*state["continuity"], *joins(state.get("planned", []))]
        if left:
            jobs.event(job_id, JobEventType.PROGRESS, {"text": f"{len(left)} scenes left; continuing"}, agent=AGENT)
            # the request's own choices go on with it: a fresh delivery must plan the way this one was asked to
            jobs.finish(payload, totals, {"build": bool(payload.state.get("build")), "scene_ids": left, "order": order,
                                          "replan": replan,
                                          "progress": {**totals, "notes": notes[:50], "failed": failed,
                                                       "episodes": state["episodes"]}}, again=True)
            return {"result": {**totals, "continued": len(left)}}
        if failed and not totals["scenes"]:
            reason = failed[0]["reason"]
            jobs.stage(job_id, Stage.SHOTS.value, "done", "No scene could be planned with David")
            jobs.set(job_id, JobStatus.FAILED, error=reason if reason.startswith("Shot Planner David") else
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
    if "remove_added" not in (payload.state.get("edit") or {}) and not llm.models_enabled():
        jobs.set(payload.job_id, JobStatus.FAILED, error=david.NO_MODEL)
        return {"failed": david.NO_MODEL}
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
    payload = DispatchPayload(job_id=uuid4(), kind=JobKind.PLAN_SCENE_DAVID, actor_user_id=uuid4(),
                              production_id=uuid4())
    return build(RunContext(ports=ports), payload, {"id": str(uuid4()), "settings": {}})

