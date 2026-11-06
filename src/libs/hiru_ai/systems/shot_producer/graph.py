"""shot_producer: design the shots that need it, and (mode `prompt`) write their prompts. Ported from
`shot_producer/engine/pipeline.py`; the code around the model is the `serialize` step's modules, the model calls are the
`shot_intent`, `craft_articulator`, `shot_writer` and `shot_critic` agents, and the design-and-review loop is the
`shot_review` panel.

Per scene, in order: the INTENT agent says what each shot is for and who is seen or only heard, and writes the scene's
coverage plan; the DoP designs the scene in one call; a REVIEW reads the drafts against the intent and the free staging
checks, and at most ONE revision is kept where it fixes more than it breaks. The job opens by naming the scenes' CRAFT
PROBLEMS, which steer the technique lookup.

    state.mode        "design" (default) | "prompt"
    state.scene_ids   scenes to work on, or
    state.shot_ids    shots to work on (their scenes are read whole: a scene is designed as one)
    state.force       re-design shots whose design is still current
    state.*           anything else is handed on to the next hop (frame_render's `frame_ids`)

A design is redone only when it is missing, out of date (its pins moved) or forced; a person's camera changes live in
`shots.camera_overrides`, which this system never writes. A prompt is a NEW version every time: earlier versions stay.

Idempotent enough for Cloud Tasks: a re-delivery of a finished job is skipped; one cut short re-designs nothing that is
already current, and at worst adds one more prompt version.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from contracts.producer import CameraSettings
from contracts.staging import AUTHORED
from hiru_ai.core import agents, llm, memory, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.registry import Registry
from hiru_ai.rag.embeddings import embed_texts
from hiru_ai.systems.shot_producer import drafts as drafts_mod
from hiru_ai.systems.shot_producer.state import State

_log = logging.getLogger(__name__)
AGENT_DP = "director_of_photography"
AGENT_INTENT = "first_assistant_director"
AGENT_REVIEW = "design_review"
AGENT_PROMPT = "prompt_writer"
Row = dict[str, Any]


@dataclass
class Design:
    """The DoP's raw answers for a scene (shot number -> entry) and the shots a revision changed (by code)."""

    answered: dict[int, Row] = field(default_factory=dict)
    revised: list[str] = field(default_factory=list)


def _plain(out: Any) -> Row:
    return dict(out.model_dump(mode="json"))


def build(ctx: RunContext, payload: DispatchPayload, production: Row) -> CompiledStateGraph[Any, Any, Any, Any]:
    jobs, scenes_port, producer = ctx.need("jobs"), ctx.need("scenes"), ctx.need("producer")
    job_id, production_id = payload.job_id, payload.production_id
    assert production_id is not None
    model_mod = parts.step("serialize", "model")
    sz = parts.step("serialize", "design")
    shots_mod, intent_mod = parts.step("serialize", "shots"), parts.step("serialize", "intent")
    tech, critique_mod = parts.step("serialize", "techniques"), parts.step("serialize", "critique")
    continuity = parts.step("serialize", "continuity")
    shot_review = parts.module("panel", "shot_review", "graph")
    enabled = llm.models_enabled()
    state_in = payload.state
    mode = str(state_in.get("mode") or "design")
    force = bool(state_in.get("force"))
    shot_ids = [str(s) for s in state_in.get("shot_ids") or []]
    targets = set(shot_ids) or None
    ledger_box: list[Any] = []  # built when the scenes are read (it needs the production's cast)

    # ── asking the agents ──────────────────────────────────────────────────────────────────────────────────────────

    def ask_intent(production_text: str, scene_text: str) -> Row:
        return _plain(agents.build("shot_intent").run({"production": production_text, "scene": scene_text}, ctx))

    def ask_craft(texts: list[str]) -> list[str]:
        return list(agents.build("craft_articulator").run({"scenes": texts}, ctx).problems)

    # ── what the job knows before it designs ───────────────────────────────────────────────────────────────────────

    def palette(scenes: list[Any], prod: Any) -> str:
        """Craft problems first (they are the sharpest queries), then shot titles and headings."""
        problems = tech.articulate(ask_craft if enabled else None, [sz.scene_text(sc) for sc in scenes])
        titles = [s.title for sc in scenes for s in sc.shots if s.title and (targets is None or s.id in targets)]
        intents = [*problems, *titles, *[sc.heading for sc in scenes]]
        search = ctx.need("search")

        def embed(queries: list[str]) -> list[list[float]]:
            return [v for v in embed_texts(queries, "shot_producer.techniques", ctx.sink()) if v is not None]

        # the production's own genre when its documents give one
        genre = memory.genre(ctx, "Sri Lankan television drama")
        found = tech.palette(intents, genre, search.techniques, embed if enabled else None)
        return "\n\n".join(b for b in (tech.problems_block(problems), found) if b)

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

    # ── designing one scene ────────────────────────────────────────────────────────────────────────────────────────

    def design_scene(scene: Any, group: list[Any], prod: Any, prefix: str,
                     canon: list[Row]) -> list[tuple[Any, Row, Row]]:
        """-> [(shot, ir, design)] for every shot in `group`, by model where it answered, else by rules. A model design
        is reviewed once; a shot's revision is kept only when the free checks find no more problems in it than in the
        first draft."""
        ledger = ledger_box[0]
        characters = [c for c in canon or [] if c.get("kind") == "character"]

        def drafts_of(answered: dict[int, Row]) -> dict[int, tuple[Row, CameraSettings, str, str, list[str]]]:
            out = {}
            for shot in group:
                entry = answered.get(shot.number)
                raw = entry or shots_mod.design_by_rules(scene, shot)
                ir, rec, why = shots_mod.finish(raw, shot, scene, prod)
                out[shot.number] = (ir, rec, why, "model" if entry else "rules", shots_mod.on_screen_ids(raw, shot))
            return out

        first: Design | None = None

        def write(ask_writer: Any, brief: Row, notes: list[str] | None) -> Design:
            nonlocal first

            def ask(production_text: str, scene_text: str) -> Row:
                return _plain(ask_writer({"production": production_text, "scene": scene_text}))

            if notes is None:
                first = Design(shots_mod.design_by_model(ask, prefix, scene, group, ledger))
                return first
            assert first is not None
            modelled = [s for s in group if s.number in first.answered]
            return Design(shots_mod.design_by_model(ask, prefix, scene, modelled, ledger, notes=notes))

        def critique(ask_critic: Any, brief: Row, draft: Design) -> list[str]:
            modelled = [s for s in group if s.number in draft.answered]
            if not modelled:
                return []
            drafts = drafts_of(draft.answered)
            free = [f"{s.code}: {p}" for s in modelled
                    for p in critique_mod.free_problems(s, drafts[s.number][0], drafts[s.number][4], characters,
                                                        scene)]
            free += critique_mod.scene_coverage_problems(scene, {
                **{s.number: s.camera(scene) for s in scene.shots}, **{n: d[1] for n, d in drafts.items()}})

            def ask(inp: Row) -> list[str]:
                critic = agents.build("shot_critic")
                if critic.uses_tools:  # a tool loop: its tools read the drafts under review, not the stored designs
                    seen = {s.id: (drafts[s.number][0], drafts[s.number][4]) for s in modelled}
                    return list(critic.run(inp, drafts_mod.reviewing(ctx, scene.id, seen)).notes)
                out = ask_critic(inp)
                if out is None:
                    raise RuntimeError("the reviewer could not answer")
                return list(out.notes)

            return critique_mod.review(ask, scene, [(s, drafts[s.number][0], drafts[s.number][4]) for s in modelled],
                                       free)

        def accept(brief: Row, draft: Design, revised: Design) -> Design:
            drafts = drafts_of(draft.answered)
            kept, done = dict(draft.answered), list(draft.revised)
            for s in group:
                entry = revised.answered.get(s.number)
                if not entry or s.number not in draft.answered:
                    continue
                ir, _, _ = shots_mod.finish(entry, s, scene, prod)
                on = shots_mod.on_screen_ids(entry, s)
                before = len(critique_mod.free_problems(s, drafts[s.number][0], drafts[s.number][4], characters,
                                                        scene))
                after = len(critique_mod.free_problems(s, ir, on, characters, scene))
                if after <= before:
                    kept[s.number] = entry
                    done.append(s.code)
            return Design(kept, done)

        notes: list[str] = []
        design = Design()
        if enabled:
            panel = shot_review.build(ctx, write=write, critique=critique, accept=accept)
            out = panel.invoke({"brief": {}})
            design, notes = out["draft"], list(out.get("notes") or [])
        drafts = drafts_of(design.answered)
        review: Row = {"notes": notes, "revised": design.revised} if notes else {}
        result = []
        for shot in group:
            ir, rec, why, planner, on = drafts[shot.number]
            row = sz.design_row(shot, ir, rec, why, planner, on, str(job_id))
            if review:
                row["review"] = review
            result.append((shot, ir, row))
        return result

    # ── the graph ──────────────────────────────────────────────────────────────────────────────────────────────────

    env: dict[str, Any] = {}  # what the read step hands to the work step: rows turned into the producer's inputs

    def read(state: State) -> State:
        scene_ids = [str(s) for s in state_in.get("scene_ids") or []] or producer.shot_scenes(production_id, shot_ids)
        canon = scenes_port.canon(production_id)
        prod = model_mod.production_input(production, canon, producer.lead_persona(production_id))
        rows = scenes_port.scenes(production_id, scene_ids) if scene_ids else []
        built = []
        for row in sorted(rows, key=lambda r: int(r.get("number") or 0)):
            sid = str(row["id"])
            built.append((row, model_mod.scene_input(row, scenes_port.shots(sid), scenes_port.lines(sid), canon, prod,
                                                     producer.neighbours(row))))
        ledger_box.append(continuity.ContinuityLedger(prod.cast))
        env["canon"], env["prod"], env["scenes"] = canon, prod, built
        return {}

    def work(state: State) -> State:
        canon, prod, built = env["canon"], env["prod"], env["scenes"]
        ledger = ledger_box[0]
        prefix: str | None = None
        designed = prompts = intents = 0
        skipped: list[str] = []
        for row, scene in built:
            label = f"Scene {scene.number}"
            wanted_design = [s for s in scene.shots if (targets is None or s.id in targets)]
            if any(force or model_mod.design_stale(s, prod) for s in wanted_design):
                written = write_intents(scene, wanted_design, prod, canon)
                if written:
                    intents += written
                    jobs.event(job_id, JobEventType.PROGRESS,
                               {"text": f"{label}: what each shot is for, for {written} shots", "scene_id": scene.id},
                               agent=AGENT_INTENT)
            group = [s for s in wanted_design if force or model_mod.design_stale(s, prod)]
            if group:
                if prefix is None and enabled:
                    prod.techniques = palette([sc for _, sc in built], prod)
                    prefix = shots_mod.production_block(prod)
                jobs.event(job_id, JobEventType.PROGRESS, {"text": f"{label}: designing {len(group)} shots",
                                                           "scene_id": scene.id}, agent=AGENT_DP)
                results = design_scene(scene, group, prod, prefix or "", canon)
                review = next((d.get("review") for _, _, d in results if d.get("review")), None)
                if review:
                    jobs.event(job_id, JobEventType.PROGRESS,
                               {"text": f"{label}: review notes: " + " · ".join(review["notes"])
                                        + (f" (revised {', '.join(review['revised'])})" if review["revised"] else ""),
                                "scene_id": scene.id}, agent=AGENT_REVIEW)
                for shot, ir, design in results:
                    scenes_port.save_design(shot.id, ir, design)
                    shot.row = {**shot.row, "ir": ir, "design": design}
                    model_mod.restage(shot, scene, canon, prod)
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
            frames = producer.accepted_frames([s.id for s in wanted])
            for shot in wanted:
                frame = frames.get(shot.id)
                if shot.frame_strategy != "carry_last_frame" and frame is None:
                    skipped.append(f"{shot.code}: no accepted first frame")
                    continue
                prompt = sz.write_prompt(shot, scene, prod, frame, str(job_id), str(payload.actor_user_id))
                prompt["version"] = producer.last_prompt_version(shot.id) + 1
                scenes_port.add_prompt(prompt)
                prompts += 1
                jobs.event(job_id, JobEventType.PROGRESS, {"text": f"{shot.code}: prompt v{prompt['version']} written",
                                                           "shot_id": shot.id}, agent=AGENT_PROMPT)
        for note in skipped:
            jobs.event(job_id, JobEventType.WARNING, {"text": note}, agent=AGENT_PROMPT)
        result: Row = {"designed": designed, "prompts": prompts, "skipped": len(skipped)}
        if intents:
            result["intents"] = intents
        if designed or prompts:
            producer.audit({"production_id": str(production_id), "actor_user_id": str(payload.actor_user_id),
                            "actor_agent": "shot_producer", "action": f"shots.{mode}", "entity": "job",
                            "entity_id": str(job_id), "diff": result})
        hand_on = {k: v for k, v in state_in.items() if k not in ("mode", "force", "previous")}
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

