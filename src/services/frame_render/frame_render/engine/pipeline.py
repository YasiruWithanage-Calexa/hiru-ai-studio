"""One frame_render job: first frames for shots, or a canon entity's reference sheet.

    state.frame_ids             frames the API created `queued` (one row per picture asked for)
    state.reference_entity_id   instead: a reference sheet for this canon entity's current card

Each frame is claim → paint → store → record, the shape of upstream's take
(`video_render/engine/take.py`):

  claim   the API inserted the row `queued`; a conditional update makes it `running`. Zero rows
          back means another delivery has it, so nothing is paid for twice.
  paint   the frame prompt is composed HERE, from the shot's IR and the camera as it stands now
          (`contracts.producer.frame_prompt`), with the canon reference sheets of the people and
          the place in the shot attached in order. A person who wears a look in the scene (the
          scene's pick, else the episode rule: `contracts.canon.looks_in_force`) gets the look
          sheet and its wardrobe instead of the base sheet and the card's. A refusal is a result,
          not a retry.
  store   the private `frames` bucket, at a path derived from the frame id (a retry overwrites).
  record  the row: the exact prompt, the references used and the PINS, so the API can say when
          the frame no longer matches its shot.

Frames of one job are painted in parallel (one action, many pictures; the job is the run).
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from contracts import sceneplan
from contracts.canon import (
    SHEET_ASPECT,
    CanonCard,
    CanonKind,
    LookFields,
    look_sheet_path,
    look_sheet_prompt,
    look_wardrobe,
    looks_in_force,
    reference_sheet_aspect,
    reference_sheet_prompt,
)
from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from contracts.producer import (
    CameraSettings,
    CastMember,
    PersonEdits,
    cast_in,
    default_camera,
    frame_prompt,
    pins_for,
    shot_canon_ids,
    shot_items,
)
from contracts.veo import ASPECT_RATIO, Orientation
from frame_render.engine.image import Picture, ProviderError, Reference, RefusedError

_logger = logging.getLogger(__name__)
AGENT = "frame_render"
WORKERS = 4
MAX_REFERENCES = 4
FAILED = "The frame could not be made. Try again in a moment."
NO_DESIGN = "This shot has no camera design yet. Design the scene first."
NOT_CONFIGURED = "Image generation is not set up on this server."
Row = dict[str, Any]
Painter = Callable[[str, str, list[Reference]], Picture]  # (prompt, aspect ratio, references)


class StoreLike(Protocol):
    def production(self, production_id: UUID) -> Row | None: ...
    def frames(self, production_id: UUID, frame_ids: list[str]) -> list[Row]: ...
    def shot(self, shot_id: str) -> Row | None: ...
    def scene(self, scene_id: str) -> Row | None: ...
    def lines(self, scene_id: str) -> list[Row]: ...
    def canon(self, production_id: UUID) -> list[Row]: ...
    def look(self, look_id: str) -> Row | None: ...
    def looks(self, production_id: UUID) -> list[Row]: ...
    def scene_looks(self, scene_id: str) -> list[Row]: ...
    def episode_number(self, episode_id: str) -> int | None: ...
    def download_reference(self, path: str) -> bytes: ...
    def claim_frame(self, frame_id: str) -> bool: ...
    def finish_frame(self, frame_id: str, fields: Row) -> None: ...
    def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None: ...
    def add_reference_asset(self, version_id: str, assets: list[Any]) -> None: ...
    def finish_look_sheet(self, look_id: str, assets: list[Any]) -> None: ...
    def audit(self, row: Row) -> None: ...


class JobsLike(Protocol):
    def check(self, payload: DispatchPayload) -> str | None: ...
    def set(self, job_id: UUID, status: JobStatus, **fields: Any) -> None: ...
    def event(self, job_id: UUID, type_: JobEventType, payload: Row, agent: str | None = None) -> None: ...
    def finish(self, payload: DispatchPayload, result: Row, next_state: Row | None = None, *,
               again: bool = False) -> None: ...


def _now() -> str:
    return datetime.now(UTC).isoformat()


def cast_member(row: Row) -> CastMember:
    current = row.get("current") or {}
    card = current.get("card") or {}
    return CastMember(id=str(row["id"]), code=str(row["code"]), name=str(row["name"]), kind=str(row["kind"]),
                      version=current.get("version"), wardrobe_anchor=str(current.get("wardrobe_anchor") or ""),
                      voice_pin=str(current.get("voice_pin") or ""), appearance=str(card.get("appearance") or ""),
                      gender=str(card.get("gender") or ""))


def _sheet_path(row: Row) -> str:
    assets = (row.get("current") or {}).get("reference_assets") or []
    first = assets[0] if assets else None
    return str(first.get("path") if isinstance(first, dict) else first or "")


class FrameJob:
    """Shared reads for every frame of one job (a scene's shots share the scene and canon)."""

    def __init__(self, store: StoreLike, production: Row) -> None:
        self.store = store
        self.production_id = UUID(str(production["id"]))
        self.aspect = ASPECT_RATIO[Orientation(production.get("orientation") or "horizontal")]
        self.canon = store.canon(self.production_id)
        self.by_id = {str(c["id"]): c for c in self.canon}
        self.members = {str(c["id"]): cast_member(c) for c in self.canon}
        self._scenes: dict[str, tuple[Row, list[Row]]] = {}
        self._all_looks: list[Row] | None = None
        self._looks: dict[str, dict[str, Mapping[str, Any]]] = {}

    def scene(self, scene_id: str) -> tuple[Row, list[Row]]:
        if scene_id not in self._scenes:
            scene = self.store.scene(scene_id) or {}
            self._scenes[scene_id] = (scene, self.store.lines(scene_id))
        return self._scenes[scene_id]

    def looks(self, scene_id: str) -> dict[str, Mapping[str, Any]]:
        """character id → the look the scene uses (`contracts.canon.looks_in_force`)."""
        if scene_id not in self._looks:
            if self._all_looks is None:
                self._all_looks = self.store.looks(self.production_id)
            scene, _ = self.scene(scene_id)
            looks: dict[str, Mapping[str, Any]] = {}
            if self._all_looks:
                episode = self.store.episode_number(str(scene["episode_id"])) if scene.get("episode_id") else None
                looks = dict(looks_in_force(self._all_looks, self.store.scene_looks(scene_id), episode))
            self._looks[scene_id] = looks
        return self._looks[scene_id]

    def _own(self, shot: Row) -> tuple[Row, list[Any], list[str]]:
        scene, lines = self.scene(str(shot["scene_id"]))
        items = sceneplan.items_for(scene.get("script") or [], lines)
        own = shot_items(items, int(shot["block_start"]), int(shot["block_end"]))
        return scene, own, cast_in(own, [c for c in self.canon if c["kind"] == "character"], PersonEdits.of(shot))

    def references(self, shot: Row) -> list[tuple[str, Reference]]:
        """The sheets of the people, then the place, in the shot that exist and can be read, in
        the order they are attached. A person wearing a look gets the look sheet; when that
        cannot be read, the base sheet. One that cannot be read is left out, not guessed at."""
        scene, _, cast_ids = self._own(shot)
        looks = self.looks(str(shot["scene_id"]))
        out: list[tuple[str, Reference]] = []
        for cid in shot_canon_ids(scene, cast_ids, PersonEdits.of(shot)):
            row = self.by_id.get(cid)
            if not row or len(out) >= MAX_REFERENCES:
                continue
            what = {"location": "the location plate for", "prop": "the reference sheet for"}.get(
                row["kind"], "the character sheet for")
            choices = [(f"{what} {row['name']}", _sheet_path(row))]
            look = looks.get(cid) if row["kind"] == "character" else None
            if look is not None:
                choices.insert(0, (f"the look sheet for {row['name']}", look_sheet_path(look)))
            for label, path in choices:
                if not path:
                    continue
                try:
                    out.append((cid, Reference(label=label, data=self.store.download_reference(path))))
                    break
                except Exception:
                    _logger.warning("%s could not be read", label, exc_info=True)
        return out

    def cast(self, shot: Row, cast_ids: list[str]) -> list[CastMember]:
        """The people in the shot, each dressed in the look the scene uses, if any."""
        looks = self.looks(str(shot["scene_id"]))
        return [self.members[c].model_copy(update={"look": look_wardrobe(looks[c])}) if c in looks
                else self.members[c] for c in cast_ids if c in self.members]

    def compose(self, shot: Row, labels: list[str]) -> tuple[str, Row]:
        """→ (the frame prompt naming exactly `labels` as its attached images, the pins)."""
        scene, own, cast_ids = self._own(shot)
        pins = pins_for(shot_version=int(shot.get("version") or 1), scene=scene, items=own, cast_ids=cast_ids,
                        versions={k: m.version for k, m in self.members.items()}, edits=PersonEdits.of(shot),
                        looks=self.looks(str(shot["scene_id"])))
        default = default_camera(str(shot.get("framing") or "MS"), heading=str(scene.get("heading") or ""),
                                 time_of_day=str(scene.get("time_of_day") or ""))
        try:
            recommended = CameraSettings.model_validate((shot.get("design") or {}).get("recommended")
                                                        or default.model_dump())
        except ValueError:
            recommended = default
        camera = recommended.with_overrides(shot.get("camera_overrides") or {})
        prompt = frame_prompt(ir=shot.get("ir") or {}, camera=camera, aspect_ratio=self.aspect,
                              cast=self.cast(shot, cast_ids),
                              references=labels, recommended_framing=recommended.framing)
        return prompt, pins.model_dump()


def render_frame(job: FrameJob, frame: Row, paint: Painter | None) -> str:
    """One frame, claim to record. → its final status."""
    fid = str(frame["id"])
    if not job.store.claim_frame(fid):
        return "skipped"
    shot = job.store.shot(str(frame["shot_id"]))
    if shot is None:
        job.store.finish_frame(fid, {"status": "failed", "error": "The shot no longer exists."})
        return "failed"
    if not shot.get("ir"):
        job.store.finish_frame(fid, {"status": "failed", "error": NO_DESIGN})
        return "failed"
    if paint is None:
        job.store.finish_frame(fid, {"status": "failed", "error": NOT_CONFIGURED})
        return "failed"
    refs = job.references(shot)
    prompt, pins = job.compose(shot, [r.label for _, r in refs])
    try:
        picture = paint(prompt, job.aspect, [r for _, r in refs])
    except RefusedError as exc:
        job.store.finish_frame(fid, {"status": "refused", "error": str(exc), "prompt": prompt, "pins": pins})
        return "refused"
    except (ProviderError, Exception):
        _logger.warning("frame %s failed", fid, exc_info=True)
        job.store.finish_frame(fid, {"status": "failed", "error": FAILED, "prompt": prompt, "pins": pins})
        return "failed"
    path = f"{job.production_id}/{shot['id']}/{fid}.png"
    job.store.upload("frames", path, picture.data, picture.mime)
    job.store.finish_frame(fid, {"status": "done", "storage_path": path, "prompt": prompt, "pins": pins,
                                 "reference_ids": [cid for cid, _ in refs], "error": None})
    return "done"


def render_reference(store: StoreLike, production: Row, entity_id: str, paint: Painter | None,
                     job_id: str) -> Row:
    """A reference sheet for an entity's CURRENT card → the `references` bucket, newest first on
    that version's `reference_assets`. Frames of later shots attach it."""
    canon = {str(c["id"]): c for c in store.canon(UUID(str(production["id"])))}
    row = canon.get(entity_id)
    current = (row or {}).get("current")
    if not row or not current:
        return {"status": "failed", "error": "This canon entry has no card yet."}
    if paint is None:
        return {"status": "failed", "error": NOT_CONFIGURED}
    kind = CanonKind(row["kind"])
    aspect = reference_sheet_aspect(kind, ASPECT_RATIO[Orientation(production.get("orientation") or "horizontal")])
    # Built again from the card each time, not read from the version's stored `reference_prompt`:
    # that was written when the version was made, so it would keep an older sheet layout alive.
    prompt = reference_sheet_prompt(kind, str(row["name"]), CanonCard.model_validate(current.get("card") or {}),
                                    aspect_ratio=aspect)
    try:
        picture = paint(prompt, aspect, [])
    except RefusedError as exc:
        return {"status": "refused", "error": str(exc)}
    except Exception:
        _logger.warning("reference sheet for %s failed", entity_id, exc_info=True)
        return {"status": "failed", "error": FAILED}
    path = f"{production['id']}/{entity_id}/{current['id']}-{job_id[:8]}.png"
    store.upload("references", path, picture.data, picture.mime)
    assets = [{"path": path, "kind": "sheet", "version": current.get("version"), "job_id": job_id,
               "created_at": _now()}, *(current.get("reference_assets") or [])]
    store.add_reference_asset(str(current["id"]), assets[:5])
    return {"status": "done", "entity_id": entity_id, "version": current.get("version")}


def render_look(store: StoreLike, production: Row, look_id: str, paint: Painter | None, job_id: str) -> Row:
    """A look sheet for a character: the base sheet goes in as image 1 and the look's words say what
    changes. The sheet lands in the `references` bucket, newest first on the look's `sheet_assets`."""
    look = store.look(look_id)
    if not look:
        return {"status": "failed", "error": "This look no longer exists."}
    canon = {str(c["id"]): c for c in store.canon(UUID(str(production["id"])))}
    row = canon.get(str(look["entity_id"]))
    base = _sheet_path(row) if row else ""
    if not row or not base:
        return {"status": "failed", "error": "Paint the base sheet first."}
    if paint is None:
        return {"status": "failed", "error": NOT_CONFIGURED}
    try:
        base_sheet = store.download_reference(base)
    except Exception:
        _logger.warning("base sheet for look %s could not be read", look_id, exc_info=True)
        return {"status": "failed", "error": FAILED}
    fields = LookFields.model_validate({k: look.get(k) or ([] if k == "ranges" else "")
                                       for k in ("name", "ranges", "outfit", "hair", "makeup", "accessories")})
    prompt = look_sheet_prompt(str(row["name"]), fields)
    try:
        picture = paint(prompt, SHEET_ASPECT,
                        [Reference(label=f"the base character sheet for {row['name']}", data=base_sheet)])
    except RefusedError as exc:
        return {"status": "refused", "error": str(exc)}
    except Exception:
        _logger.warning("look sheet %s failed", look_id, exc_info=True)
        return {"status": "failed", "error": FAILED}
    current = row.get("current") or {}
    path = f"{production['id']}/{row['id']}/looks/{look_id}-{job_id[:8]}.png"
    store.upload("references", path, picture.data, picture.mime)
    assets = [{"path": path, "kind": "look", "base_version": current.get("version"), "job_id": job_id,
               "created_at": _now()}, *(look.get("sheet_assets") or [])]
    store.finish_look_sheet(look_id, assets[:5])
    return {"status": "done", "look_id": look_id}


def run(payload: DispatchPayload, store: StoreLike, jobs: JobsLike, paint: Painter | None) -> Row:
    skip = jobs.check(payload)
    if skip:
        return {"skipped": skip}
    job_id, production_id = payload.job_id, payload.production_id
    assert production_id is not None
    jobs.set(job_id, JobStatus.RUNNING)
    production = store.production(production_id)
    if production is None:
        jobs.set(job_id, JobStatus.DONE, result={"skipped": "production deleted"})
        return {"skipped": "production deleted"}
    actor = str(payload.actor_user_id)

    entity_id = payload.state.get("reference_entity_id")
    if entity_id:
        result = render_reference(store, production, str(entity_id), paint, str(job_id))
        jobs.event(job_id, JobEventType.PROGRESS if result["status"] == "done" else JobEventType.WARNING,
                   {"text": "Reference sheet ready" if result["status"] == "done" else result["error"]}, agent=AGENT)
        if result["status"] == "done":
            store.audit({"production_id": str(production_id), "actor_user_id": actor, "actor_agent": AGENT,
                         "action": "canon.reference_sheet", "entity": "canon", "entity_id": str(entity_id),
                         "diff": {"job_id": str(job_id)}})
        jobs.finish(payload, result)
        return result

    look_id = payload.state.get("look_id")
    if look_id:
        result = render_look(store, production, str(look_id), paint, str(job_id))
        jobs.event(job_id, JobEventType.PROGRESS if result["status"] == "done" else JobEventType.WARNING,
                   {"text": "Look sheet ready" if result["status"] == "done" else result["error"]}, agent=AGENT)
        if result["status"] == "done":
            store.audit({"production_id": str(production_id), "actor_user_id": actor, "actor_agent": AGENT,
                         "action": "canon.look_sheet_made", "entity": "canon_look", "entity_id": str(look_id),
                         "diff": {"job_id": str(job_id)}})
        jobs.finish(payload, result)
        return result

    frames = store.frames(production_id, [str(f) for f in payload.state.get("frame_ids") or []])
    job = FrameJob(store, production)
    counts = {"done": 0, "failed": 0, "refused": 0, "skipped": 0}

    def one(frame: Row) -> tuple[Row, str]:
        try:
            return frame, render_frame(job, frame, paint)
        except Exception:
            _logger.exception("frame %s crashed", frame.get("id"))
            store.finish_frame(str(frame["id"]), {"status": "failed", "error": FAILED})
            return frame, "failed"

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for frame, status in pool.map(one, frames):
            counts[status] += 1
            if status != "skipped":
                jobs.event(job_id, JobEventType.PROGRESS if status == "done" else JobEventType.WARNING,
                           {"text": "Frame ready" if status == "done" else f"Frame {status}",
                            "frame_id": str(frame["id"]), "shot_id": str(frame["shot_id"]), "status": status},
                           agent=AGENT)
    if counts["done"]:
        store.audit({"production_id": str(production_id), "actor_user_id": actor, "actor_agent": AGENT,
                     "action": "frames.render", "entity": "job", "entity_id": str(job_id), "diff": counts})
    jobs.finish(payload, counts)
    return counts
