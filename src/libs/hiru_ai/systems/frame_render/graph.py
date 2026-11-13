"""frame_render: first frames for shots, or a canon entity's reference sheet, or a look sheet. Ported from
`frame_render/engine/pipeline.py`; the composing is the `frame_compose` step and the picture check the `frame_inspector`
agent, both found by id.

    state.frame_ids             frames the API created `queued` (one row per picture asked for)
    state.reference_entity_id   instead: a reference sheet for this canon entity's current card
    state.look_id               instead: a look sheet for this look

Each frame is claim -> paint -> store -> record:

  claim   the API inserted the row `queued`; a conditional update makes it `running`. Zero rows back means another
          delivery has it, so nothing is paid for twice.
  paint   the prompt is composed from the shot's IR and the camera as it stands now, with the sheets of the people the
          camera SEES and the place attached in order. A refusal is a result, not a retry.
  store   the private `frames` bucket, at a path derived from the frame id (a retry overwrites).
  record  the row: the exact prompt, the references used and the PINS, so the API can say when the frame no longer
          matches its shot; and its CHECKS: an on-screen person painted without a sheet, and what a vision model sees
          in the picture against what the shot expects (advisory; a frame is never repainted by it).

Frames of one job are painted in parallel (one action, many pictures; the job is the run).
"""
from __future__ import annotations

import base64
import contextvars
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from contracts import safe_depiction
from contracts.canon import scene_conditions
from contracts.frame_brief import BLACK_PLATE
from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from contracts.memory import genre_of
from contracts.producer import DRAFT_LABEL, FrameStage, frame_stage
from hiru_ai.core import agents, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.ports import ImageRefused, Reference
from hiru_ai.core.registry import Registry
from hiru_ai.core.settings import get_settings
from hiru_ai.systems.frame_render.state import State

_log = logging.getLogger(__name__)
AGENT = "frame_render"
WORKERS = 4
FAILED = "The frame could not be made. Try again in a moment."
NO_DESIGN = "This shot has no camera design yet. Design the scene first."
NOT_CONFIGURED = "Image generation is not set up on this server."
NO_DRAFT = "The accepted draft could not be read. Accept a draft again, or paint the final without one."
Row = dict[str, Any]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _compose(op: str, **payload: Any) -> Row:
    return parts.module("step", "frame_compose", "step").run({"op": op, **payload})


def _genre(ctx: RunContext, production_id: UUID) -> str:
    """The production's genre phrase for the frame's lead (plan/2026-11-12b), from its `series` facts; "" when it has
    none or the memory cannot be read (the lead then stays general)."""
    port = ctx.ports.memory
    if port is None:
        return ""
    try:
        return genre_of(port.entries(production_id))
    except Exception:
        _log.warning("production memory could not be read for the genre; the general lead is used", exc_info=True)
        return ""


class Scenes:
    """The reads every frame of one job shares (a scene's shots share the scene, its lines and the looks it uses).
    Loaded the first time a scene is asked for; the worker threads may race to load one, which costs a read, no more."""

    def __init__(self, ctx: RunContext, production: Row) -> None:
        self.ctx, self.production = ctx, production
        self.production_id = UUID(str(production["id"]))
        self.canon: list[Row] = ctx.need("scenes").canon(self.production_id)
        self.genre = _genre(ctx, self.production_id)
        self._worlds: dict[str, Row] = {}
        self._all_looks: list[Row] | None = None
        self._lock = threading.Lock()

    def world(self, scene_id: str) -> Row:
        """A step "world": the production, the canon, the scene with its lines, and the looks it uses."""
        with self._lock:
            found = self._worlds.get(scene_id)
        if found is not None:
            return found
        frames, scenes = self.ctx.need("frames"), self.ctx.need("scenes")
        scene = frames.scene(scene_id) or {}
        looks: dict[str, Any] = {}
        picks = frames.scene_looks(scene_id)
        with self._lock:
            if self._all_looks is None:
                self._all_looks = frames.looks(self.production_id)
            all_looks = self._all_looks
        if all_looks:
            episode = frames.episode_number(str(scene["episode_id"])) if scene.get("episode_id") else None
            looks = _compose("looks", all_looks=all_looks, scene_looks=picks, episode=episode)["looks"]
        shots = scenes.shots(scene_id)  # plan/2026-11-11b: the same-setup frame of a later shot of a setup
        accepted = frames.accepted_finals([str(s["id"]) for s in shots]) if any(s.get("slate") for s in shots) else {}
        world = {"production": self.production, "canon": self.canon, "scene": scene, "lines": scenes.lines(scene_id),
                 "looks": looks, "shots": shots, "accepted": accepted, "genre": self.genre,
                 "conditions": scene_conditions(picks)}
        with self._lock:
            self._worlds[scene_id] = world
        return world


def _download(ctx: RunContext, path: str, bucket: str = "references") -> bytes:
    return bytes(ctx.need("files").download(bucket, path))


def _references(ctx: RunContext, world: Row, shot: Row) -> list[tuple[str, str, Reference]]:
    """(id, role, picture) for the sheets of the people the camera SEES, the place, what they hold and the same-setup
    frame, that exist and can be read, in the order they are attached. One that cannot be read is left out, not guessed
    at."""
    out: list[tuple[str, str, Reference]] = []
    for want in _compose("references", **world, shot=shot)["references"]:
        for choice in want["choices"]:
            try:
                data = _download(ctx, choice["path"], str(choice.get("bucket") or "references"))
                out.append((want["id"], str(want.get("role") or ""), Reference(label=choice["label"], data=data)))
                break
            except Exception:
                _log.warning("%s could not be read", choice["label"], exc_info=True)
    return out


def _draft_picture(ctx: RunContext, scenes: Scenes, draft_id: str, shot_id: str) -> Reference:
    """The picture of a draft of THIS shot (a frame id from another shot is never attached). Raises when it cannot be
    read: a final the person chose to paint from its draft is not silently painted without it."""
    row = next((f for f in ctx.need("frames").frames(scenes.production_id, [draft_id])
                if str(f["shot_id"]) == shot_id and frame_stage(f) == FrameStage.DRAFT
                and f.get("status") == "done" and f.get("storage_path")), None)
    if row is None:
        raise LookupError(draft_id)
    return Reference(label=DRAFT_LABEL, data=bytes(ctx.need("files").download("frames", str(row["storage_path"]))))


def _vision_enabled() -> bool:
    return bool(get_settings().openai.model_vision)


def _inspect(ctx: RunContext, picture_data: bytes, mime: str, expected: Row) -> Row | None:
    """What the vision model sees, or None: no key, switched off (`OPENAI__MODEL_VISION=""`), or a failed call. The
    frame is still done."""
    from hiru_ai.core import llm

    if not (llm.models_enabled() and _vision_enabled()):
        return None
    try:
        out = agents.build("frame_inspector").run(
            {"image_b64": base64.b64encode(picture_data).decode(), "mime": mime, "seen": expected["seen"],
             "unseen": expected["unseen"], "frame": expected["frame"], "hands": expected.get("hands") or ""}, ctx)
    except Exception:
        _log.warning("the frame could not be inspected", exc_info=True)
        return None
    return dict(out.model_dump())


def render_frame(ctx: RunContext, scenes: Scenes, frame: Row) -> str:
    """One frame, claim to record. -> its final status."""
    frames, files, paint = ctx.need("frames"), ctx.need("files"), ctx.ports.images
    fid = str(frame["id"])
    if not frames.claim_frame(fid):
        return "skipped"
    shot = frames.shot(str(frame["shot_id"]))
    if shot is None:
        frames.finish_frame(fid, {"status": "failed", "error": "The shot no longer exists."})
        return "failed"
    if not shot.get("ir"):
        frames.finish_frame(fid, {"status": "failed", "error": NO_DESIGN})
        return "failed"
    if paint is None:
        frames.finish_frame(fid, {"status": "failed", "error": NOT_CONFIGURED})
        return "failed"
    world = scenes.world(str(shot["scene_id"]))
    if _compose("plate", **world, shot=shot)["plate"]:  # plan/2026-11-12b: a cut to black or a title card
        return black_plate(ctx, scenes, frame, shot)
    refs = _references(ctx, world, shot)
    pictures = [r for _, _, r in refs]
    sheets = [cid for cid, role, _ in refs if role != "setup"]  # `reference_ids` holds canon ids only
    draft = frame_stage(frame) == FrameStage.DRAFT
    if frame.get("draft_id") and not draft:  # a final painted from the shot's accepted draft: it goes in FIRST
        try:
            pictures.insert(0, _draft_picture(ctx, scenes, str(frame["draft_id"]), str(shot["id"])))
        except Exception:
            _log.warning("draft %s of frame %s could not be read", frame["draft_id"], fid, exc_info=True)
            frames.finish_frame(fid, {"status": "failed", "error": NO_DRAFT})
            return "failed"
    composed = _compose("compose", **world, shot=shot, labels=[r.label for r in pictures])
    prompt, pins = composed["prompt"], composed["pins"]
    found = safe_depiction.blocking(prompt)
    if found:  # stopped before the image model is paid (plan/2026-11-10b); the legacy pipeline does the same
        frames.finish_frame(fid, {"status": "refused", "error": safe_depiction.frame_error(found), "prompt": prompt,
                                  "pins": pins})
        return "refused"
    aspect = parts.module("step", "frame_compose").production_aspect(scenes.production)
    try:
        picture = paint(prompt, aspect, pictures, draft=draft)
    except ImageRefused as exc:
        frames.finish_frame(fid, {"status": "refused", "error": str(exc), "prompt": prompt, "pins": pins})
        return "refused"
    except Exception:
        _log.warning("frame %s failed", fid, exc_info=True)
        frames.finish_frame(fid, {"status": "failed", "error": FAILED, "prompt": prompt, "pins": pins})
        return "failed"
    path = f"{scenes.production_id}/{shot['id']}/{fid}.png"
    files.upload("frames", path, picture.data, picture.mime)
    expected = _compose("expected", **world, shot=shot)
    answer = _inspect(ctx, picture.data, picture.mime, expected)
    checks = _compose("checks", **world, shot=shot, attached=sheets, answer=answer)["checks"]
    frames.finish_frame(fid, {"status": "done", "storage_path": path, "prompt": prompt, "pins": pins,
                              "reference_ids": sheets, "error": None, "checks": checks})
    return "done"


def black_plate(ctx: RunContext, scenes: Scenes, frame: Row, shot: Row) -> str:
    """A black plate, made by code and stored like a painted frame (plan/2026-11-12b): no model, no references."""
    frames, files = ctx.need("frames"), ctx.need("files")
    compose = parts.module("step", "frame_compose")
    fid = str(frame["id"])
    path = f"{scenes.production_id}/{shot['id']}/{fid}.png"
    files.upload("frames", path, compose.black_png(compose.production_aspect(scenes.production)), "image/png")
    frames.finish_frame(fid, {"status": "done", "storage_path": path, "prompt": BLACK_PLATE, "pins": {},
                              "reference_ids": [], "error": None, "checks": []})
    return "done"


def render_reference(ctx: RunContext, scenes: Scenes, entity_id: str, job_id: str) -> Row:
    """A reference sheet for an entity's CURRENT card -> the `references` bucket, newest first on that version's
    `reference_assets`. Frames of later shots attach it."""
    frames, files, paint = ctx.need("frames"), ctx.need("files"), ctx.ports.images
    production = scenes.production
    row = next((c for c in scenes.canon if str(c["id"]) == entity_id), None)
    current = (row or {}).get("current")
    if not row or not current:
        return {"status": "failed", "error": "This canon entry has no card yet."}
    if paint is None:
        return {"status": "failed", "error": NOT_CONFIGURED}
    made = _compose("reference_sheet", production=production, entity=row)
    try:
        picture = paint(made["prompt"], made["aspect"], [], sheet=True)
    except ImageRefused as exc:
        return {"status": "refused", "error": str(exc)}
    except Exception:
        _log.warning("reference sheet for %s failed", entity_id, exc_info=True)
        return {"status": "failed", "error": FAILED}
    path = f"{production['id']}/{entity_id}/{current['id']}-{job_id[:8]}.png"
    files.upload("references", path, picture.data, picture.mime)
    assets = [{"path": path, "kind": "sheet", "version": current.get("version"), "job_id": job_id,
               "created_at": _now()}, *(current.get("reference_assets") or [])]
    frames.add_reference_asset(str(current["id"]), assets[:5])
    return {"status": "done", "entity_id": entity_id, "version": current.get("version")}


def render_look(ctx: RunContext, scenes: Scenes, look_id: str, job_id: str) -> Row:
    """A look sheet for a character: the base sheet goes in as image 1 and the look's words say what changes. The sheet
    lands in the `references` bucket, newest first on the look's `sheet_assets`."""
    frames, files, paint = ctx.need("frames"), ctx.need("files"), ctx.ports.images
    production = scenes.production
    look = frames.look(look_id)
    if not look:
        return {"status": "failed", "error": "This look no longer exists."}
    row = next((c for c in scenes.canon if str(c["id"]) == str(look["entity_id"])), None)
    base = parts.module("step", "frame_compose").sheet_path(row) if row else ""
    if not row or not base:
        return {"status": "failed", "error": "Paint the base sheet first."}
    if paint is None:
        return {"status": "failed", "error": NOT_CONFIGURED}
    try:
        base_sheet = _download(ctx, base)
    except Exception:
        _log.warning("base sheet for look %s could not be read", look_id, exc_info=True)
        return {"status": "failed", "error": FAILED}
    made = _compose("look_sheet", entity=row, look=look)
    try:
        picture = paint(made["prompt"], made["aspect"],
                        [Reference(label=f"the base character sheet for {row['name']}", data=base_sheet)],
                        sheet=True)
    except ImageRefused as exc:
        return {"status": "refused", "error": str(exc)}
    except Exception:
        _log.warning("look sheet %s failed", look_id, exc_info=True)
        return {"status": "failed", "error": FAILED}
    current = row.get("current") or {}
    path = f"{production['id']}/{row['id']}/looks/{look_id}-{job_id[:8]}.png"
    files.upload("references", path, picture.data, picture.mime)
    assets = [{"path": path, "kind": "look", "base_version": current.get("version"), "job_id": job_id,
               "created_at": _now()}, *(look.get("sheet_assets") or [])]
    frames.finish_look_sheet(look_id, assets[:5])
    return {"status": "done", "look_id": look_id}


def build(ctx: RunContext, payload: DispatchPayload, production: Row) -> CompiledStateGraph[Any, Any, Any, Any]:
    jobs, frames = ctx.need("jobs"), ctx.need("frames")
    job_id, production_id = payload.job_id, UUID(str(production["id"]))
    actor = str(payload.actor_user_id)
    scenes: Scenes | None = None

    def loaded() -> Scenes:
        nonlocal scenes
        if scenes is None:  # only a job that paints reads the canon
            scenes = Scenes(ctx, production)
        return scenes

    def audit(action: str, entity: str, entity_id: str, diff: Row) -> None:
        frames.audit({"production_id": str(production_id), "actor_user_id": actor, "actor_agent": AGENT,
                      "action": action, "entity": entity, "entity_id": entity_id, "diff": diff})

    def sheet(done_text: str, action: str, entity: str, key: str, make: Any) -> Any:
        def node(state: State) -> State:
            result = make(ctx, loaded(), str(payload.state[key]), str(job_id))
            jobs.event(job_id, JobEventType.PROGRESS if result["status"] == "done" else JobEventType.WARNING,
                       {"text": done_text if result["status"] == "done" else result["error"]}, agent=AGENT)
            if result["status"] == "done":
                audit(action, entity, str(payload.state[key]), {"job_id": str(job_id)})
            return {"result": result}

        return node

    def paint_frames(state: State) -> State:
        rows = frames.frames(production_id, [str(f) for f in payload.state.get("frame_ids") or []])
        job = loaded()
        counts = {"done": 0, "failed": 0, "refused": 0, "skipped": 0}

        def one(frame: Row) -> tuple[Row, str]:
            try:
                return frame, render_frame(ctx, job, frame)
            except Exception:
                _log.exception("frame %s crashed", frame.get("id"))
                frames.finish_frame(str(frame["id"]), {"status": "failed", "error": FAILED})
                return frame, "failed"

        # each frame runs in a copy of this context: a thread of the pool does not inherit it by itself
        copies = [contextvars.copy_context() for _ in rows]  # copied here, in this thread, one per task
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for frame, status in pool.map(lambda pair: pair[0].run(one, pair[1]), zip(copies, rows, strict=True)):
                counts[status] += 1
                if status != "skipped":
                    jobs.event(job_id, JobEventType.PROGRESS if status == "done" else JobEventType.WARNING,
                               {"text": "Frame ready" if status == "done" else f"Frame {status}",
                                "frame_id": str(frame["id"]), "shot_id": str(frame["shot_id"]), "status": status},
                               agent=AGENT)
        if counts["done"]:
            audit("frames.render", "job", str(job_id), counts)
        return {"result": counts}

    def route(state: State) -> str:
        if payload.state.get("reference_entity_id"):
            return "reference"
        return "look" if payload.state.get("look_id") else "frames"

    g: Any = StateGraph(State)
    g.add_node("frames", paint_frames)
    g.add_node("reference", sheet("Reference sheet ready", "canon.reference_sheet", "canon", "reference_entity_id",
                                  render_reference))
    g.add_node("look", sheet("Look sheet ready", "canon.look_sheet_made", "canon_look", "look_id", render_look))
    g.add_conditional_edges(START, route, ["frames", "reference", "look"])
    for node in ("frames", "reference", "look"):
        g.add_edge(node, END)
    return g.compile()


def run(payload: DispatchPayload, ctx: RunContext) -> dict[str, Any]:
    jobs, scenes = ctx.need("jobs"), ctx.need("scenes")
    skip = jobs.check(payload)
    if skip:
        return {"skipped": skip}
    job_id, production_id = payload.job_id, payload.production_id
    assert production_id is not None
    jobs.set(job_id, JobStatus.RUNNING)
    production = scenes.production(production_id)
    if production is None:
        jobs.set(job_id, JobStatus.DONE, result={"skipped": "production deleted"})
        return {"skipped": "production deleted"}
    result: dict[str, Any] = build(ctx, payload, production).invoke({})["result"]
    jobs.finish(payload, result)
    return result


def blank(registry: Registry | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    """The graph with nothing to run, for drawing and for the generated contract tests."""
    from dataclasses import replace
    from uuid import uuid4

    from contracts.jobs import JobKind
    from hiru_ai.core.context import Ports
    from hiru_ai.core.fakes import FakeFrames, FakeJobs

    ports = replace(Ports(), jobs=FakeJobs(), frames=FakeFrames())
    payload = DispatchPayload(job_id=uuid4(), kind=JobKind.FRAME_RENDER, actor_user_id=uuid4(),
                              production_id=uuid4(), state={"frame_ids": []})
    return build(RunContext(ports=ports), payload, {"id": str(uuid4())})
