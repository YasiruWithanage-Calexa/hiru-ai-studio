"""shot_producer: design the shots that need it ("Recommend settings"). Design only (2026-11-21): the prompts are the
`shot_prompts` system's.

Per scene: the INTENT agent (`shot_intent`) says what each shot is for and who is seen or only heard, and writes the
scene's coverage plan; then the CAMERA AGENT (plan/2026-11-20c) designs the camera of the shots that need it, one call
for the scene, keeping the planner's IR (refitted to the shot's beats). With no model, the shot keeps the rule camera
and the job says so.

A shot with no planner's IR cannot be designed: it says "Plan this scene with Raphael first". The old DoP panel
(`shot_writer`, reviewed by `shot_critic` with `craft_articulator`'s craft problems) that designed such shots is retired
(2026-11-21: Raphael is the planner; every future planner writes an IR the same way).

    state.mode        "design" (default) | "camera_ask" (plan/2026-11-20c D11 d: the Camera agent redesigns the wanted
                      shots' camera, `state.note` the person's words).
    state.scene_ids   scenes to work on, or
    state.shot_ids    shots to work on (their scenes are read whole: a scene is designed as one)
    state.force       re-design shots whose design is still current
    state.*           anything else is handed on to the next hop (shot_prompts' `shot_prompts`, frame_render's
                      `frame_ids`)

A design is redone only when it is missing, out of date (its pins moved) or forced; a person's camera changes live in
`shots.camera_overrides`, which this system never writes.

Idempotent enough for Cloud Tasks: a re-delivery of a finished job is skipped; one cut short re-designs nothing that is
already current.
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from contracts.memory import genre_of
from contracts.staging import AUTHORED
from hiru_ai.core import agents, camera, llm, memory, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.registry import Registry
from hiru_ai.systems.shot_producer.state import State

_log = logging.getLogger(__name__)
AGENT_INTENT = "first_assistant_director"
WARNINGS_KEPT = 10  # the job's result carries its first warnings, for the screen that started it (plan §7)
MODES = ("design", "camera_ask")
PLAN_FIRST = "Plan this scene with Raphael first: the shot has no plan to design from"
Row = dict[str, Any]


def _plain(out: Any) -> Row:
    return dict(out.model_dump(mode="json"))


def build(ctx: RunContext, payload: DispatchPayload, production: Row) -> CompiledStateGraph[Any, Any, Any, Any]:
    jobs, scenes_port, producer = ctx.need("jobs"), ctx.need("scenes"), ctx.need("producer")
    job_id, production_id = payload.job_id, payload.production_id
    assert production_id is not None
    model_mod = parts.step("serialize", "model")
    sz = parts.step("serialize", "design")
    shots_mod, intent_mod = parts.step("serialize", "shots"), parts.step("serialize", "intent")
    enabled = llm.models_enabled()
    state_in = payload.state
    mode = str(state_in.get("mode") or "design")
    if mode not in MODES:  # "prompt" and "shot_prompt" are the shot_prompts system's (2026-11-21)
        raise ValueError(f"shot_producer: unknown mode {mode!r}")
    force = bool(state_in.get("force"))
    ask_note = " ".join(str(state_in.get("note") or "").split())[:600]  # mode "camera_ask": the person's words
    shot_ids = [str(s) for s in state_in.get("shot_ids") or []]
    targets = set(shot_ids) or None

    def ask_intent(production_text: str, scene_text: str) -> Row:
        return _plain(agents.build("shot_intent").run({"production": production_text, "scene": scene_text}, ctx))

    def write_intents(scene: Any, wanted: list[Any], prod: Any, canon: list[Row]) -> int:
        """Intents for the wanted shots that need one, and the scene's coverage plan when it needs one. A person's
        intent or plan is never replaced. -> how many intents were written."""
        def agent_owned(shot: Any) -> bool:
            current = shot.intent
            return current is None or current.by not in AUTHORED

        need = [s for s in wanted if agent_owned(s) and (force or s.intent_needed())]
        current_plan = scene.plan
        plan_needed = scene.plan_needed() or (force and (current_plan is None or current_plan.by not in AUTHORED))
        if not need and not plan_needed:
            return 0
        for s in need:
            sz.drop_agent_intent(s)
            model_mod.restage(s, scene, canon, prod)
        # The plan is about the whole scene, so the model reads every shot when it writes one.
        asked = scene.shots if plan_needed else need
        written, plan = intent_mod.write(ask_intent if enabled else None, scene, asked, prod, plan=plan_needed)
        for s in need:
            it = written[s.number]
            producer.save_intent(s.id, it.model_dump())
            s.row = {**s.row, "intent": it.model_dump()}
            model_mod.restage(s, scene, canon, prod)
        if plan is not None:
            producer.save_coverage(scene.id, plan.model_dump())
            scene.row = {**scene.row, "coverage": plan.model_dump()}
        return len(need)

    # ── the Camera agent (plan/2026-11-20c D11 c, d) ────────────────────────────────────────────────────────────────

    def camera_scene(row: Row, scene: Any, group: list[Any], prod: Any, canon: list[Row], skipped: list[str], *,
                     ask: str = "") -> int:
        """The Camera agent on `group` (the scene's other shots are its context): one call, the IR kept and refitted,
        the design re-pinned for a stale shot. `ask`: the person's note ("Ask Camera"), one-shot mode. -> designed."""
        packet = camera.packet_of(ctx, row)
        whole = not ask and {s.id for s in group} == {s.id for s in scene.shots}
        for shot in group:  # the IR refitted to the shot's beats, the pins of the shot as it is now (D5)
            ir, _, why = shots_mod.finish({**(shot.row.get("ir") or {}),
                                             "rationale": (shot.row.get("design") or {}).get("rationale") or ""},
                                            shot, scene, prod)
            old = dict(shot.row.get("design") or {})
            planner = str(old.get("planner") or "rules")
            on = list(old.get("on_screen") or shot.staged.on_screen)
            fresh = sz.design_row(shot, ir, shot.recommended(scene), why, planner, on, str(job_id))
            shot.row = {**shot.row, "ir": ir, "design": {**old, **fresh}}
        got = camera.design(ctx, scene, prod, packet=packet, line_rows=env["raw"].get(scene.id, ([], []))[1],
                            focus=None if whole else [s.id for s in group], note=ask, job_id=str(job_id))
        skipped.extend(got.warnings)
        done = 0
        for shot in group:
            design = got.designs.get(shot.id, shot.row["design"])
            scenes_port.save_design(shot.id, shot.row["ir"], design)
            shot.row = {**shot.row, "design": design}
            model_mod.restage(shot, scene, canon, prod)
            done += 1
            block = design.get("camera") or {}
            jobs.event(job_id, JobEventType.PROGRESS,
                       {"text": f"{shot.code}: {design['recommended']['lens']} · "
                                f"{design['recommended']['movement'].lower()}"
                                + (" (the rule camera: the agent could not design it)"
                                   if block.get("state") == "not designed" else ""),
                        "shot_id": shot.id, "planner": design.get("planner")}, agent=camera.AGENT)
        return done

    env: dict[str, Any] = {}  # what the read step hands to the work step: rows turned into the producer's inputs

    def read(state: State) -> State:
        scene_ids = [str(s) for s in state_in.get("scene_ids") or []] or producer.shot_scenes(production_id, shot_ids)
        canon = scenes_port.canon(production_id)
        prod = model_mod.production_input(production, canon, producer.lead_persona(production_id))
        prod.genre = genre_of(memory.entries(ctx))  # plan/2026-11-12b: the FORMAT line and the video Style
        rows = scenes_port.scenes(production_id, scene_ids) if scene_ids else []
        built = []
        raw: dict[str, tuple[list[Row], list[Row]]] = {}  # scene id → (its shot rows, its line rows)
        for row in sorted(rows, key=lambda r: int(r.get("number") or 0)):
            sid = str(row["id"])
            raw[sid] = (scenes_port.shots(sid), scenes_port.lines(sid))
            built.append((row, model_mod.scene_input(row, raw[sid][0], raw[sid][1], canon, prod,
                                                     producer.neighbours(row))))
        env["raw"] = raw
        env["canon"], env["prod"], env["scenes"] = canon, prod, built
        return {}

    def work(state: State) -> State:
        canon, prod, built = env["canon"], env["prod"], env["scenes"]
        designed = intents = 0
        skipped: list[str] = []
        for row, scene in built:
            label = f"Scene {scene.number}"
            wanted = [s for s in scene.shots if (targets is None or s.id in targets)]
            skipped.extend(f"{s.code}: {PLAN_FIRST}" for s in wanted if not s.row.get("ir"))
            if mode == "camera_ask":  # D11 d: "Ask Camera" redoes the wanted shots' camera only
                if not camera.on():
                    skipped.append(camera.NEEDS_MODEL)
                    continue
                asked = [s for s in wanted if s.row.get("ir")]
                if asked:
                    jobs.event(job_id, JobEventType.PROGRESS, {"text": f"{label}: the Camera agent redesigns "
                                                                       f"{', '.join(s.code for s in asked)}",
                                                               "scene_id": scene.id}, agent=camera.AGENT)
                    designed += camera_scene(row, scene, asked, prod, canon, skipped,
                                             ask=ask_note or "Design it again.")
                continue
            group = [s for s in wanted if s.row.get("ir") and (force or model_mod.design_stale(s, prod))]
            if not group:
                continue
            written = write_intents(scene, group, prod, canon)
            if written:
                intents += written
                jobs.event(job_id, JobEventType.PROGRESS,
                           {"text": f"{label}: what each shot is for, for {written} shots", "scene_id": scene.id},
                           agent=AGENT_INTENT)
            # D11 c: the planner's IR is kept, the Camera agent designs the camera (no model: the rule camera, said)
            jobs.event(job_id, JobEventType.PROGRESS, {"text": f"{label}: the Camera agent designs {len(group)} "
                                                               "shots", "scene_id": scene.id}, agent=camera.AGENT)
            designed += camera_scene(row, scene, group, prod, canon, skipped)
        notes = list(dict.fromkeys(skipped))
        for note in notes:
            jobs.event(job_id, JobEventType.WARNING, {"text": note}, agent=camera.AGENT)
        result: Row = {"designed": designed, "skipped": len(notes)}
        if notes:  # why a shot was not designed, for the screen that asked
            result["warnings"] = notes[:WARNINGS_KEPT]
        if intents:
            result["intents"] = intents
        if designed:
            producer.audit({"production_id": str(production_id), "actor_user_id": str(payload.actor_user_id),
                            "actor_agent": "shot_producer", "action": f"shots.{mode}", "entity": "job",
                            "entity_id": str(job_id), "diff": result})
        # the next hop gets the rest: shot_prompts its `shot_prompts`, frame_render its `frame_ids`
        hand_on = {k: v for k, v in state_in.items() if k not in ("mode", "force", "previous", "note")}
        jobs.finish(payload, result, hand_on)
        return {"result": result}

    g: Any = StateGraph(State)
    g.add_node("read", read)
    g.add_node("work", work)
    g.add_edge(START, "read")
    g.add_edge("read", "work")
    g.add_edge("work", END)
    return g.compile()


def run(payload: DispatchPayload, ctx: RunContext) -> dict[str, Any]:
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
    memory.report(ctx, jobs, payload.job_id)  # entries that disagree or ask for what cannot be made
    result: dict[str, Any] = build(ctx, payload, production).invoke({})["result"]
    return result


def blank(registry: Registry | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    """The graph with nothing to run, for drawing and for the generated contract tests."""
    from dataclasses import replace
    from uuid import uuid4

    from contracts.jobs import JobKind
    from hiru_ai.core.context import Ports
    from hiru_ai.core.fakes import FakeJobs, FakeProducer, FakeScenes

    ports = replace(Ports(), jobs=FakeJobs(), scenes=FakeScenes(), producer=FakeProducer())
    payload = DispatchPayload(job_id=uuid4(), kind=JobKind.SHOT_PRODUCE, actor_user_id=uuid4(),
                              production_id=uuid4())
    return build(RunContext(ports=ports), payload, {"id": str(uuid4()), "settings": {}})

