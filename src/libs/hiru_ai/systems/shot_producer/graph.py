"""shot_producer: design the shots that need it, and (mode `prompt`) write their prompts. Ported from
`shot_producer/engine/pipeline.py`; the code around the model is the `serialize` step's modules, the model calls are the
`shot_intent`, `craft_articulator`, `shot_writer` and `shot_critic` agents, and the design-and-review loop is the
`shot_review` panel.

Per scene, in order: the INTENT agent says what each shot is for and who is seen or only heard, and writes the scene's
coverage plan; the DoP designs the scene in one call; a REVIEW reads the drafts against the intent and the free staging
checks, and at most ONE revision is kept where it fixes more than it breaks. The job opens by naming the scenes' CRAFT
PROBLEMS, which steer the technique lookup.

    state.mode        "design" (default) | "prompt" | "shot_prompt" | "camera_ask" (plan/2026-11-20c D11 d: the Camera
                      agent redesigns the wanted shots' camera, `state.note` the person's words).
                      "shot_prompt" (plan/2026-11-20d D4 c, "Rewrite prompts"): the `shot_prompter` agent writes each
                      wanted shot's first frame and video together and stores them on the shot
                      (`design.shot_prompt`); a frame drawn from the old one is then out of date, never redrawn here.
                      "prompt" ("Generate video prompt", D4 b) writes each wanted shot's video prompt from its stored
                      shot prompt: no call while it is current, ONE video-only call when only the video is out of
                      date, a full call when there is none; every fact and spoken word is put in by the
                      `video_prompt` step. No fallback: an answer that fails its checks twice, a missing packet or no
                      model writes NO new version, and the job says why (a WARNING, and `warnings` in its result).
    state.shot_prompts  shots whose first frame is about to be drawn ("Draw first frame", D4 a): each one with no
                      current shot prompt gets one before the frame job (the next hop) paints it
    state.scene_ids   scenes to work on, or
    state.shot_ids    shots to work on (their scenes are read whole: a scene is designed as one)
    state.force       re-design shots whose design is still current
    state.*           anything else is handed on to the next hop (frame_render's `frame_ids`)

With a model to call (plan/2026-11-20c D11 c), a scene whose shots have a planner's IR
(Raphael's, Zora's, Sable's) is designed by the Camera agent instead of the DoP: the IR is kept (refitted to the shot's
beats), the camera is the agent's, one call for the scene.

A design is redone only when it is missing, out of date (its pins moved) or forced; a person's camera changes live in
`shots.camera_overrides`, which this system never writes. A prompt is a NEW version every time: earlier versions stay
as they were made.

Idempotent enough for Cloud Tasks: a re-delivery of a finished job is skipped; one cut short re-designs nothing that is
already current, and at worst adds one more prompt version.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from contracts import picture_pins
from contracts.canon import wardrobe_by_code
from contracts.frame_brief import agent_camera
from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from contracts.memory import genre_of
from contracts.producer import CameraSettings
from contracts.staging import AUTHORED
from hiru_ai.core import agents, camera, llm, memory, parts
from hiru_ai.core import shot_prompts as prompter
from hiru_ai.core.context import RunContext
from hiru_ai.core.registry import Registry
from hiru_ai.rag.embeddings import embed_texts
from hiru_ai.systems.shot_producer import drafts as drafts_mod
from hiru_ai.systems.shot_producer.state import State

_log = logging.getLogger(__name__)
AGENT_DP = "director_of_photography"
AGENT_INTENT = "first_assistant_director"
AGENT_REVIEW = "design_review"
AGENT_PROMPT = "shot_prompter"  # the job's events about prompts (plan/2026-11-20d: one agent writes both)
WARNINGS_KEPT = 10  # the job's result carries its first warnings, for the screen that started it (plan §7)
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
    ask_note = " ".join(str(state_in.get("note") or "").split())[:600]  # mode "camera_ask": the person's words
    shot_ids = [str(s) for s in state_in.get("shot_ids") or []]
    targets = set(shot_ids) or None
    before_frames = {str(s) for s in state_in.get("shot_prompts") or []}  # D4 a: "Draw first frame" is next
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

    def by_camera(group: list[Any]) -> bool:
        """The Camera agent designs these shots: it is on and each has a planner's IR to keep."""
        return camera.on() and bool(group) and all(s.row.get("ir") for s in group)

    # ── the graph ──────────────────────────────────────────────────────────────────────────────────────────────────

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
        ledger_box.append(continuity.ContinuityLedger(prod.cast))
        env["canon"], env["prod"], env["scenes"] = canon, prod, built
        return {}

    def frame_world(row: Row, canon: list[Row]) -> Row:
        """The frame_compose world of a scene: what the shot screen and the renderer build a frame's prompt from."""
        frames = ctx.ports.frames
        sid = str(row["id"])
        shot_rows, line_rows = env["raw"].get(sid, ([], []))
        looks: Row = {}
        accepted: Row = {}
        if frames is not None:
            all_looks = frames.looks(production_id)
            if all_looks:
                episode = frames.episode_number(str(row["episode_id"])) if row.get("episode_id") else None
                looks = parts.module("step", "frame_compose", "step").run(
                    {"op": "looks", "all_looks": all_looks, "scene_looks": frames.scene_looks(sid),
                     "episode": episode})["looks"]
            if any(s.get("slate") for s in shot_rows):
                accepted = frames.accepted_finals([str(s["id"]) for s in shot_rows])
        live = {str(s["id"]): s for s in shot_rows}
        return {"production": production, "canon": canon, "scene": row, "lines": line_rows, "looks": looks,
                "shots": list(live.values()), "accepted": accepted}

    def prompt_context(row: Row, scene: Any, prod: Any, canon: list[Row], skipped: list[str]) -> Row | None:
        """What every shot prompt of a scene needs (plan/2026-11-20d): the scene part of the brief (the same for every
        shot: it caches), the line ids, the frame world, the looks; None and a warning when the scene's packet is not
        usable (plan/2026-11-20b D5: no packet, no prompt)."""
        step = parts.step("video_prompt", "step")
        facts = parts.step("video_prompt", "facts")
        packet, why = facts.usable_packet(ctx.ports.breakdown, row)  # D5
        lids = facts.line_ids_for(packet, env["raw"].get(scene.id, ([], []))[1]) if packet is not None else None
        if packet is None or lids is None:
            skipped.append(f"Scene {scene.number}: no shot prompt written: "
                           + (why or "the packet's spoken lines do not match the scene's lines: refresh the scene's "
                                     "breakdown"))
            return None
        world = frame_world(row, canon)
        world_rows = {str(s["id"]): s for s in world["shots"]}
        return {"scene_part": step.run({"op": "brief", "scene": {"packet": packet, "genre": prod.genre,
                                                                  "style_note": prod.style_note}})["scene"],
                "lids": lids, "world": parts.module("step", "frame_compose").World.of(world), "rows": world_rows,
                # plan/2026-11-18: each person dressed in the look the scene uses (the look sheet the take attaches)
                "wardrobe": wardrobe_by_code(world["looks"], canon)}

    def live(shot: Any, pc: Row) -> Row:
        """The shot's row as the frame world reads it, with what this job has written to it."""
        return {**pc["rows"].get(shot.id, {}), **shot.row}

    def save_shot_prompt(shot: Any, record: Row) -> None:
        design = {**(shot.row.get("design") or {}), "shot_prompt": record}
        scenes_port.save_design(shot.id, shot.row["ir"], design)
        shot.row = {**shot.row, "design": design}

    def write_shot_prompt(shot: Any, scene: Any, prod: Any, pc: Row, frame: Row | None, skipped: list[str], *,
                          mode: str = "both") -> Row | None:
        """One shot's prompts by the agent (D4), stored on the shot. -> the record, or None (and a warning)."""
        facts = prompter.facts_for(shot, scene, prod, frame, lids=pc["lids"], wardrobe=pc["wardrobe"])
        row = live(shot, pc)
        stored = (row.get("design") or {}).get("shot_prompt")
        got = prompter.write(ctx, facts, scene_part=pc["scene_part"], pins=pc["world"].pins_now(row), mode=mode,
                             stored=stored if isinstance(stored, dict) else None, job_id=str(job_id))
        if got.record is None:
            skipped.append(f"{shot.code}: shot prompt not written: {got.failed}")
            return None
        save_shot_prompt(shot, got.record)
        jobs.event(job_id, JobEventType.PROGRESS,
                   {"text": f"{shot.code}: " + ("video prompt rewritten from the drawn frame" if mode == "video_only"
                                                else "first frame and video prompt written")
                            + (" (repaired once)" if got.repaired else ""), "shot_id": shot.id}, agent=AGENT_PROMPT)
        return got.record

    def shot_prompts(row: Row, scene: Any, prod: Any, canon: list[Row], skipped: list[str], wanted: list[Any], *,
                     rewrite: bool) -> int:
        """D4 a / c: a shot prompt for each wanted shot ("Rewrite prompts": every one; before a frame: only those with
        none current). -> how many were written."""
        if not wanted:
            return 0
        pc = prompt_context(row, scene, prod, canon, skipped)
        if pc is None:
            return 0
        need = [s for s in wanted if rewrite or pc["world"].shot_prompt_reasons(live(s, pc))]
        if need and not prompter.on():
            skipped.append(f"Scene {scene.number}: {prompter.NEEDS_MODEL}: "
                           + ("the first frame keeps the code's words" if not rewrite else "nothing was rewritten"))
            return 0
        frames = producer.accepted_frames([s.id for s in need]) if need else {}
        written = 0
        for shot in sorted(need, key=lambda s: s.number):
            if not shot.row.get("ir"):
                skipped.append(f"{shot.code}: no camera design yet: design the scene first")
                continue
            # "Write prompts" (2026-11-21): only the video when only the video is out of date (a camera move, the
            # script, no timecodes yet): the opening and the drawn frame are kept; else both
            need_now = prompter.needs(pc["world"], live(shot, pc)) if rewrite else "both"
            mode_now = "video_only" if need_now == "video_only" else "both"
            if write_shot_prompt(shot, scene, prod, pc, frames.get(shot.id), skipped, mode=mode_now) is not None:
                written += 1
        return written

    def video_prompts(row: Row, scene: Any, prod: Any, canon: list[Row], skipped: list[str], *,
                      assemble_only: bool = False) -> int:
        """Mode "prompt" (plan/2026-11-20d D4 b): each wanted shot's video prompt, in number order, from its stored shot
        prompt: no call while it is current; ONE video-only call (the stored opening and frame kept) when only the
        video is out of date; a full call when there is none or the picture moved. -> how many versions were written."""
        step = parts.step("video_prompt", "step")
        facts_mod = parts.step("video_prompt", "facts")
        wanted = sorted((s for s in scene.shots if targets is None or s.id in targets), key=lambda s: s.number)
        if not wanted:
            return 0
        pc = prompt_context(row, scene, prod, canon, skipped)
        if pc is None:
            return 0
        frames = producer.accepted_frames([s.id for s in wanted])
        sp_step = parts.module("step", "shot_prompt", "step")
        written = 0
        for shot in wanted:
            frame = frames.get(shot.id)
            if shot.frame_strategy != "carry_last_frame" and frame is None:
                skipped.append(f"{shot.code}: no accepted first frame")
                continue
            need = prompter.needs(pc["world"], live(shot, pc))
            record: Row | None = (live(shot, pc).get("design") or {}).get("shot_prompt") if need == "current" \
                else None
            if record is None and assemble_only:  # after "Write prompts": never a second call for a shot that failed
                continue
            if record is None:
                if not prompter.on():  # D4: no code-only video prompt
                    skipped.append(f"{shot.code}: video prompt not written: {prompter.NEEDS_MODEL}")
                    continue
                record = write_shot_prompt(shot, scene, prod, pc, frame, skipped, mode=need)
                if record is None:
                    continue
            clip = facts_mod.clip_facts(shot, scene, prod, frame, lids=pc["lids"], wardrobe=pc["wardrobe"])
            direction = sp_step.run({"op": "direction", "answer": record})["direction"]
            made = step.run({"op": "assemble", "direction": direction, "clip": clip,
                             "repaired": bool(record.get("repaired"))})
            camera_now = shot.camera(scene)
            prompt = {"production_id": prod.id, "shot_id": shot.id, "sections": made["sections"],
                      "prose": made["prose"], "model": f"{sz.VIDEO_MODEL} · {shot.duration_s} s · {prod.aspect_ratio}",
                      "ir": dict(shot.row.get("ir") or {}), "camera": camera_now.model_dump(),
                      "checks": made["checks"], "frame_id": str(frame["id"]) if frame else None,
                      "pins": picture_pins.pinned(shot.pins, camera_now, shot.recommended(scene),
                                                  agent_camera(shot.row)),
                      "job_id": str(job_id), "created_by": str(payload.actor_user_id)}
            prompt["version"] = producer.last_prompt_version(shot.id) + 1
            scenes_port.add_prompt(prompt)
            written += 1
            jobs.event(job_id, JobEventType.PROGRESS, {"text": f"{shot.code}: video prompt v{prompt['version']} "
                                                               "written" + (" from its shot prompt" if need == "current"
                                                                            else ""),
                                                       "shot_id": shot.id}, agent=AGENT_PROMPT)
        return written

    def work(state: State) -> State:
        canon, prod, built = env["canon"], env["prod"], env["scenes"]
        ledger = ledger_box[0]
        prefix: str | None = None
        designed = prompts = intents = framed = 0
        skipped: list[str] = []
        for row, scene in built:
            label = f"Scene {scene.number}"
            wanted_design = [s for s in scene.shots if (targets is None or s.id in targets)]
            if mode == "camera_ask":  # D11 d: "Ask Camera" redoes the wanted shots' camera only
                if not camera.on():
                    skipped.append(camera.NEEDS_MODEL)
                    continue
                asked = [s for s in wanted_design if s.row.get("ir")]
                skipped.extend(f"{s.code}: no camera design yet: design the scene first" for s in wanted_design
                               if not s.row.get("ir"))
                if asked:
                    jobs.event(job_id, JobEventType.PROGRESS, {"text": f"{label}: the Camera agent redesigns "
                                                                       f"{', '.join(s.code for s in asked)}",
                                                               "scene_id": scene.id}, agent=camera.AGENT)
                    designed += camera_scene(row, scene, asked, prod, canon, skipped,
                                             ask=ask_note or "Design it again.")
                continue
            if any(force or model_mod.design_stale(s, prod) for s in wanted_design):
                written = write_intents(scene, wanted_design, prod, canon)
                if written:
                    intents += written
                    jobs.event(job_id, JobEventType.PROGRESS,
                               {"text": f"{label}: what each shot is for, for {written} shots", "scene_id": scene.id},
                               agent=AGENT_INTENT)
            group = [s for s in wanted_design if force or model_mod.design_stale(s, prod)]
            if group and by_camera(group):  # D11 c: the planner's IR is kept, the Camera agent designs the camera
                jobs.event(job_id, JobEventType.PROGRESS, {"text": f"{label}: the Camera agent designs {len(group)} "
                                                                   "shots", "scene_id": scene.id}, agent=camera.AGENT)
                designed += camera_scene(row, scene, group, prod, canon, skipped)
                group = []
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

            if mode == "shot_prompt":  # D4 c: "Write prompts", the shot header's one button
                framed += shot_prompts(row, scene, prod, canon, skipped,
                                       [s for s in scene.shots if targets is None or s.id in targets], rewrite=True)
                # ...then the video prompt of each shot with an accepted first frame: its shot prompt is current now,
                # so it is assembled by code with no call (a shot with no frame gets it when one is accepted)
                quiet: list[str] = []
                prompts += video_prompts(row, scene, prod, canon, quiet, assemble_only=True)
                skipped.extend(n for n in quiet if not n.endswith("no accepted first frame"))
            elif before_frames:  # D4 a: the frames job is next; a shot with no current shot prompt gets one first
                framed += shot_prompts(row, scene, prod, canon, skipped,
                                       [s for s in scene.shots if s.id in before_frames], rewrite=False)
            if mode != "prompt":
                continue
            prompts += video_prompts(row, scene, prod, canon, skipped)
        for note in skipped:
            jobs.event(job_id, JobEventType.WARNING, {"text": note}, agent=AGENT_PROMPT)
        result: Row = {"designed": designed, "prompts": prompts, "skipped": len(skipped)}
        if mode in ("prompt", "shot_prompt") and skipped:  # why a shot got no prompt, for the screen that asked
            result["warnings"] = skipped[:WARNINGS_KEPT]
        if framed:
            result["shot_prompts"] = framed
        if intents:
            result["intents"] = intents
        if designed or prompts or framed:
            producer.audit({"production_id": str(production_id), "actor_user_id": str(payload.actor_user_id),
                            "actor_agent": "shot_producer", "action": f"shots.{mode}", "entity": "job",
                            "entity_id": str(job_id), "diff": result})
        hand_on = {k: v for k, v in state_in.items() if k not in ("mode", "force", "previous", "note",
                                                                  "shot_prompts")}
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

