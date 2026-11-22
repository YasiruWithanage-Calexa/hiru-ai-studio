"""shot_prompts: write the prompts of shots whose camera design is current (2026-11-21). The `shot_prompter` agent
writes each shot's first frame and video from ONE opening state and stores it on the shot (`design.shot_prompt`); each
video prompt is then assembled from it by the `video_prompt` step, which puts in every fact and spoken word.

This system only writes prompts. It never designs: a shot whose design is missing or out of date is skipped with
"Recommend settings first" (the shot producer designs; plan/2026-11-20c). Before 2026-11-21 this lived inside the shot
producer, which redesigned a stale shot on its way to the prompts.

    state.mode        "write" (the shot header's one "Write prompts" button): the agent writes each wanted shot's first
                      frame and video together (only the video when only the video is out of date, so the drawn frame
                      is kept); then each shot with an accepted first frame gets its video prompt assembled by code,
                      with no further call.
                      "video" ("Generate video prompt"): each wanted shot's video prompt from its stored shot prompt: no
                      call while it is current, ONE video-only call when only the video is out of date, a full call
                      when there is none.
                      "frames" (a hop before frame_render, "Draw first frame"): each shot in `state.shot_prompts` with
                      no current shot prompt gets one before the frame is painted from it.
    state.shot_prompts  the shots the "frames" mode writes for
    state.scene_ids   scenes to work on, or
    state.shot_ids    shots to work on
    state.*           anything else is handed on to the next hop (frame_render's `frame_ids`)

No fallback: an answer that fails its checks twice, a missing packet or no model writes NO new version, and the job
says why (a WARNING, and `warnings` in its result). A video prompt is a NEW version every time.
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from contracts import picture_pins
from contracts.canon import wardrobe_by_code
from contracts.frame_brief import agent_camera
from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from contracts.memory import genre_of
from contracts.producer import PersonEdits
from hiru_ai.core import memory, parts
from hiru_ai.core import shot_prompts as prompter
from hiru_ai.core.context import RunContext
from hiru_ai.core.registry import Registry
from hiru_ai.systems.shot_prompts.state import State

_log = logging.getLogger(__name__)
AGENT = "shot_prompter"  # the job's events (one agent writes the first frame and the video)
WARNINGS_KEPT = 10  # the job's result carries its first warnings, for the screen that started it
DESIGN_FIRST = "Recommend settings first: its camera design is missing or out of date"
NO_ACCEPTED_FRAME = "no accepted first frame"
MODES = ("write", "video", "frames")
Row = dict[str, Any]


def build(ctx: RunContext, payload: DispatchPayload, production: Row) -> CompiledStateGraph[Any, Any, Any, Any]:
    jobs, scenes_port, producer = ctx.need("jobs"), ctx.need("scenes"), ctx.need("producer")
    job_id, production_id = payload.job_id, payload.production_id
    assert production_id is not None
    model_mod = parts.step("serialize", "model")
    sz = parts.step("serialize", "design")
    state_in = payload.state
    # a hop after the shot producer in "Draw first frame" gets no mode (the producer keeps its own): it is "frames"
    mode = str(state_in.get("mode") or ("frames" if "shot_prompts" in state_in else "write"))
    if mode not in MODES:
        raise ValueError(f"shot_prompts: unknown mode {mode!r}")
    shot_ids = [str(s) for s in state_in.get("shot_ids") or []]
    before_frames = {str(s) for s in state_in.get("shot_prompts") or []}
    targets = (before_frames if mode == "frames" else set(shot_ids)) or None
    env: dict[str, Any] = {}

    def read(state: State) -> State:
        ids = sorted(targets or [])
        scene_ids = [str(s) for s in state_in.get("scene_ids") or []] or producer.shot_scenes(production_id, ids)
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
        env.update(raw=raw, canon=canon, prod=prod, scenes=built)
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
        live_rows = {str(s["id"]): s for s in shot_rows}
        return {"production": production, "canon": canon, "scene": row, "lines": line_rows, "looks": looks,
                "shots": list(live_rows.values()), "accepted": accepted}

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
                          how: str = "both") -> Row | None:
        """One shot's prompts by the agent (D4), stored on the shot. -> the record, or None (and a warning)."""
        facts = prompter.facts_for(shot, scene, prod, frame, lids=pc["lids"], wardrobe=pc["wardrobe"])
        row = live(shot, pc)
        stored = (row.get("design") or {}).get("shot_prompt")
        record = stored if isinstance(stored, dict) else None
        # plan/2026-11-22c (option 1): the video is written from the stored words only while the frame was drawn
        # from them; otherwise it is said, never guessed
        if how == "video_only" and frame is not None and shot.frame_strategy != "carry_last_frame" \
                and not prompter.drawn_from(record, frame):
            skipped.append(f"{shot.code}: video prompt not rewritten: {prompter.FRAME_NOT_FROM_PROMPT}")
            return None
        got = prompter.write(ctx, facts, scene_part=pc["scene_part"], pins=pc["world"].pins_now(row), mode=how,
                             stored=stored if isinstance(stored, dict) else None, job_id=str(job_id))
        if got.record is None:
            skipped.append(f"{shot.code}: shot prompt not written: {got.failed}")
            return None
        save_shot_prompt(shot, got.record)
        jobs.event(job_id, JobEventType.PROGRESS,
                   {"text": f"{shot.code}: " + ("video prompt rewritten from the drawn frame" if how == "video_only"
                                                else "first frame and video prompt written")
                            + (" (repaired once)" if got.repaired else ""), "shot_id": shot.id}, agent=AGENT)
        return got.record

    def designed(wanted: list[Any], prod: Any, skipped: list[str]) -> list[Any]:
        """The wanted shots whose camera design is current; each other one is named with "Recommend settings first"
        (this system never designs)."""
        ready = []
        for shot in wanted:
            if not shot.row.get("ir") or model_mod.design_stale(shot, prod):
                skipped.append(f"{shot.code}: {DESIGN_FIRST}")
            else:
                ready.append(shot)
        return ready

    def shot_prompts(row: Row, scene: Any, prod: Any, canon: list[Row], skipped: list[str], wanted: list[Any], *,
                     rewrite: bool) -> int:
        """A shot prompt for each wanted shot ("Write prompts": every one; before a frame: only those with none
        current). -> how many were written."""
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
            # "Write prompts" (2026-11-21): only the video when only the video is out of date (a camera move, the
            # script, no timecodes yet): the opening and the drawn frame are kept; else both
            need_now = prompter.needs(pc["world"], live(shot, pc)) if rewrite else "both"
            how = "video_only" if need_now == "video_only" else "both"
            if write_shot_prompt(shot, scene, prod, pc, frames.get(shot.id), skipped, how=how) is not None:
                written += 1
        return written

    def video_prompts(row: Row, scene: Any, prod: Any, canon: list[Row], skipped: list[str], wanted: list[Any], *,
                      assemble_only: bool = False) -> int:
        """Each wanted shot's video prompt, in number order, from its stored shot prompt: no call while it is current;
        ONE video-only call (the stored opening and frame kept) when only the video is out of date; a full call when
        there is none or the picture moved. `assemble_only` (after "Write prompts"): never a call. -> versions made."""
        step = parts.step("video_prompt", "step")
        facts_mod = parts.step("video_prompt", "facts")
        wanted = sorted(wanted, key=lambda s: s.number)
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
                skipped.append(f"{shot.code}: {NO_ACCEPTED_FRAME}")
                continue
            need = prompter.needs(pc["world"], live(shot, pc))
            record: Row | None = (live(shot, pc).get("design") or {}).get("shot_prompt") if need == "current" \
                else None
            if record is None and assemble_only:  # never a second call for a shot whose prompts failed
                continue
            if record is None:
                if not prompter.on():  # D4: no code-only video prompt
                    skipped.append(f"{shot.code}: video prompt not written: {prompter.NEEDS_MODEL}")
                    continue
                record = write_shot_prompt(shot, scene, prod, pc, frame, skipped, how=need)
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
                                                  agent_camera(shot.row),
                                                  video_note=PersonEdits.of(shot.row).video_note),
                      "job_id": str(job_id), "created_by": str(payload.actor_user_id)}
            prompt["version"] = producer.last_prompt_version(shot.id) + 1
            scenes_port.add_prompt(prompt)
            written += 1
            jobs.event(job_id, JobEventType.PROGRESS, {"text": f"{shot.code}: video prompt v{prompt['version']} "
                                                               "written" + (" from its shot prompt" if need == "current"
                                                                            else ""),
                                                       "shot_id": shot.id}, agent=AGENT)
        return written

    def work(state: State) -> State:
        canon, prod, built = env["canon"], env["prod"], env["scenes"]
        prompts = framed = 0
        skipped: list[str] = []
        for row, scene in built:
            wanted = designed([s for s in scene.shots if targets is None or s.id in targets], prod, skipped)
            if mode == "write":  # the shot header's one button
                framed += shot_prompts(row, scene, prod, canon, skipped, wanted, rewrite=True)
                # ...then the video prompt of each shot with an accepted first frame: its shot prompt is current now,
                # so it is assembled by code with no call (a shot with no frame gets it when one is accepted)
                quiet: list[str] = []
                prompts += video_prompts(row, scene, prod, canon, quiet, wanted, assemble_only=True)
                skipped.extend(n for n in quiet if not n.endswith(NO_ACCEPTED_FRAME))
            elif mode == "frames":  # the frames job is next; a shot with no current shot prompt gets one first
                framed += shot_prompts(row, scene, prod, canon, skipped, wanted, rewrite=False)
            else:
                prompts += video_prompts(row, scene, prod, canon, skipped, wanted)
        for note in skipped:
            jobs.event(job_id, JobEventType.WARNING, {"text": note}, agent=AGENT)
        result: Row = {"prompts": prompts, "skipped": len(skipped)}
        if skipped:  # why a shot got no prompt, for the screen that asked
            result["warnings"] = skipped[:WARNINGS_KEPT]
        if framed:
            result["shot_prompts"] = framed
        if prompts or framed:
            producer.audit({"production_id": str(production_id), "actor_user_id": str(payload.actor_user_id),
                            "actor_agent": "shot_prompts", "action": f"shot_prompts.{mode}", "entity": "job",
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
    payload = DispatchPayload(job_id=uuid4(), kind=JobKind.SHOT_PROMPTS, actor_user_id=uuid4(),
                              production_id=uuid4())
    return build(RunContext(ports=ports), payload, {"id": str(uuid4()), "settings": {}})
