"""Screen 4, Prompt & handoff (PLAN.md §10, §13 Phase 5).

    GET   .../shots/{id}/handoff        the prompt, its handoff checks, the opening frame, the takes
    POST  .../shots/{id}/takes          a take a person brings back from Flow (MP4 / MOV / WebM)
    POST  .../takes/{id}/accept|reject  one accepted take per shot; accepting pulls its last frame
                                        for the next shot when that shot carries on from it
    GET   .../scenes/{id}/bundle        the scene's prompts and opening frames as one zip

Checks are run on every read (`contracts.handoff.check_prompt`): they report, they never edit.
Takes and frames reach browsers only through `/files/{ticket}`. No costs anywhere.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field

from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos, Row
from api.routers.production import (
    FrameView,
    Loaded,
    PromptView,
    load,
    load_shot,
    shot_view,
)
from api.services import media_links
from api.services.assemble import Assembler, get_assembler
from api.services.production import ShotState, camera_checks
from contracts.handoff import (
    DEFAULT_BANNED_TERMS,
    MAX_TAKE_BYTES,
    LineNow,
    ShotNow,
    SpeakerNow,
    TakeStatus,
    blocking,
    check_prompt,
    video_kind,
)
from contracts.producer import Check, PromptSection
from contracts.production import ProductionSettings
from contracts.roles import Permission
from contracts.veo import FrameStrategy

router = APIRouter(prefix="/v1/productions/{production_id}", tags=["handoff"])
ReposDep = Annotated[Repos, Depends(get_repos)]
AssemblerDep = Annotated[Assembler, Depends(get_assembler)]
CanView = Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))]
CanHandoff = Annotated[ProductionAccess, Depends(require_permission(Permission.HANDOFF))]
LENGTH_TOLERANCE_S = 0.5


class TakeView(BaseModel):
    id: UUID
    label: str  # "Take 2"
    prompt_version: int | None
    status: TakeStatus
    reason: str | None
    url: str  # /files/{ticket}, never a storage URL
    duration_s: float | None
    duration_note: str  # "" or "7.2 s; the shot is 8 s"
    created_at: str


class HandoffView(BaseModel):
    shot_id: UUID
    scene_id: UUID
    code: str
    duration_s: int
    frame_strategy: FrameStrategy
    prompt: PromptView | None
    checks: list[Check]  # the handoff checks, on the prompt as it would be copied now
    ready: bool  # a current prompt with no failing check
    opening_frame: FrameView | None  # the accepted frame (generated, uploaded or carried)
    carried_from: str  # "S02" when this shot opens on the previous take's last frame
    next_carries: bool  # accepting a take here makes the next shot's first frame
    takes: list[TakeView]
    accepted_take_id: UUID | None


class RejectTake(BaseModel):
    reason: str = Field(default="", max_length=300)


def _settings(ld: Loaded) -> ProductionSettings:
    return ProductionSettings.model_validate(ld.production.get("settings") or {})


def _neighbour(ld: Loaded, st: ShotState, step: int) -> ShotState | None:
    number = int(st.row["number"]) + step
    return next((s for s in ld.states if int(s.row["number"]) == number), None)


def handoff_checks(ld: Loaded, st: ShotState) -> list[Check]:
    """`contracts.handoff.check_prompt` on the shot's latest prompt, against the shot as it is now."""
    if st.prompt is None:
        return []
    sections = [PromptSection.model_validate(s) for s in st.prompt.get("sections") or []]
    sinhala = [seg.sinhala for s in sections for seg in s.segments if seg.sinhala is not None]
    by_line = {str(ln["id"]): ln for ln in ld.lines}
    lines = [LineNow(text=i.text, speaker=i.speaker, overrun_s=float((by_line.get(i.line_id or "") or {})
                                                                     .get("overrun_s") or 0))
             for i in st.items if i.is_line]
    speaker_ids = list(dict.fromkeys(i.speaker_id for i in st.items if i.is_line and i.speaker_id))
    speakers = [SpeakerNow(name=c.name, voice_pin=c.voice_pin) for c in st.cast if c.id in speaker_ids]
    shot = ShotNow(code=st.code, duration_s=int(st.row["duration_s"]), aspect_ratio=ld.aspect,
                   sound_mode=str(st.row.get("sound_mode") or "ambient"), lines=lines, speakers=speakers)
    return check_prompt(prose=str(st.prompt.get("prose") or ""), sinhala=sinhala, shot=shot,
                        banned_terms=[*DEFAULT_BANNED_TERMS, *_settings(ld).banned_terms])


def _take_view(take: Row, index: int, shot_seconds: int) -> TakeView:
    duration = take.get("duration_s")
    note = ""
    if duration is not None and abs(float(duration) - shot_seconds) > LENGTH_TOLERANCE_S:
        note = f"{float(duration):.1f} s; the shot is {shot_seconds} s"
    return TakeView(id=take["id"], label=f"Take {index}", prompt_version=take.get("prompt_version"),
                    status=TakeStatus(take["status"]), reason=take.get("reason"),
                    url=media_links.url("takes", str(take["storage_path"])),
                    duration_s=float(duration) if duration is not None else None, duration_note=note,
                    created_at=str(take["created_at"]))


async def _view(repos: Repos, access: ProductionAccess, shot_id: UUID) -> HandoffView:
    ld, st = await load_shot(repos, access, shot_id)
    view = shot_view(ld, st, camera_checks(ld.states)[st.id])
    takes = await repos.takes.list_for_shots([st.id])
    checks = handoff_checks(ld, st)
    previous, following = _neighbour(ld, st, -1), _neighbour(ld, st, 1)
    carried = st.row.get("frame_strategy") == FrameStrategy.CARRY_LAST_FRAME
    opening = next((f for f in view.frames if f.accepted), None)
    accepted = next((t for t in takes if t["status"] == TakeStatus.ACCEPTED), None)
    return HandoffView(
        shot_id=st.row["id"], scene_id=st.row["scene_id"], code=st.code, duration_s=int(st.row["duration_s"]),
        frame_strategy=FrameStrategy(st.row.get("frame_strategy") or "generate"), prompt=view.prompt,
        checks=checks, ready=bool(view.prompt) and not (view.prompt and view.prompt.stale) and not blocking(checks),
        opening_frame=opening, carried_from=previous.code if carried and previous else "",
        next_carries=bool(following and following.row.get("frame_strategy") == FrameStrategy.CARRY_LAST_FRAME),
        takes=[_take_view(t, i, int(st.row["duration_s"])) for i, t in enumerate(takes, start=1)],
        accepted_take_id=accepted["id"] if accepted else None)


async def _audit(repos: Repos, access: ProductionAccess, action: str, entity_id: str, diff: Row) -> None:
    await repos.audit.record(action=action, entity="take", entity_id=entity_id, actor_user_id=access.user.id,
                             production_id=access.production_id, diff=diff)


# ── reads ──────────────────────────────────────────────────────────────────────────────────


@router.get("/shots/{shot_id}/handoff", response_model=HandoffView)
async def get_handoff(production_id: UUID, shot_id: UUID, access: CanView, repos: ReposDep) -> HandoffView:
    return await _view(repos, access, shot_id)


# ── takes ──────────────────────────────────────────────────────────────────────────────────


@router.post("/shots/{shot_id}/takes", response_model=HandoffView, status_code=status.HTTP_201_CREATED)
async def upload_take(production_id: UUID, shot_id: UUID, file: Annotated[UploadFile, File()], access: CanHandoff,
                      repos: ReposDep, assembler: AssemblerDep) -> HandoffView:
    """A video generated in Flow from this shot's prompt. Checked by content; probed for its length."""
    _, st = await load_shot(repos, access, shot_id)
    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data += chunk
        if len(data) > MAX_TAKE_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE,
                                f"Takes can be at most {MAX_TAKE_BYTES // (1024 * 1024)} MB.")
    kind = video_kind(bytes(data))
    if kind is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Upload an MP4, MOV or WebM video.")
    ext, mime = kind
    take_id = str(uuid4())
    path = f"{production_id}/{shot_id}/{take_id}.{ext}"
    await repos.storage.upload("takes", path, bytes(data), mime)
    probe = await assembler.probe("takes", path)
    await repos.takes.create({
        "id": take_id, "production_id": str(production_id), "shot_id": str(shot_id),
        "prompt_id": str(st.prompt["id"]) if st.prompt else None,
        "prompt_version": int(st.prompt["version"]) if st.prompt else None, "storage_path": path, "mime": mime,
        "bytes": len(data), "duration_s": probe.duration_s if probe else None, "uploaded_by": str(access.user.id)})
    await _audit(repos, access, "take.upload", take_id, {"shot_id": str(shot_id), "bytes": len(data)})
    return await _view(repos, access, shot_id)


async def _take(repos: Repos, production_id: UUID, take_id: UUID) -> Row:
    take = await repos.takes.get(production_id, take_id)
    if take is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Take not found.")
    return take


async def carry_last_frame(repos: Repos, assembler: Assembler, ld: Loaded, st: ShotState, take: Row,
                           user_id: UUID) -> str:
    """The accepted take's last frame becomes the next shot's accepted first frame, when the next
    shot carries on from this one. → the next shot's code, or "" when there is nothing to do or
    the frame could not be made (the person can upload it by hand)."""
    following = _neighbour(ld, st, 1)
    if not following or following.row.get("frame_strategy") != FrameStrategy.CARRY_LAST_FRAME:
        return ""
    frame_id = str(uuid4())
    out = f"{ld.production['id']}/{following.id}/carried-{frame_id}.png"
    path = await assembler.last_frame("takes", str(take["storage_path"]), "frames", out)
    if not path:
        return ""
    await repos.frames.create_many([{
        "id": frame_id, "production_id": str(ld.production["id"]), "shot_id": following.id, "status": "done",
        "storage_path": path, "prompt": f"The last frame of {st.code}'s accepted take.",
        "pins": following.pins.model_dump(), "created_by": str(user_id)}])
    await repos.frames.accept(UUID(following.id), UUID(frame_id), user_id)
    await repos.takes.update(UUID(str(take["id"])), {"last_frame_path": path})
    return following.code


@router.post("/takes/{take_id}/accept", response_model=HandoffView)
async def accept_take(production_id: UUID, take_id: UUID, access: CanHandoff, repos: ReposDep,
                      assembler: AssemblerDep) -> HandoffView:
    take = await _take(repos, production_id, take_id)
    ld, st = await load_shot(repos, access, UUID(str(take["shot_id"])))
    if not await repos.takes.accept(UUID(st.id), take_id, access.user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Someone accepted another take meanwhile. Reload the shot.")
    carried = await carry_last_frame(repos, assembler, ld, st, take, access.user.id)
    await _audit(repos, access, "take.accept", str(take_id), {"shot_id": st.id, "carried_to": carried})
    return await _view(repos, access, UUID(st.id))


@router.post("/takes/{take_id}/reject", response_model=HandoffView)
async def reject_take(production_id: UUID, take_id: UUID, body: RejectTake, access: CanHandoff,
                      repos: ReposDep) -> HandoffView:
    take = await _take(repos, production_id, take_id)
    await repos.takes.update(take_id, {"status": TakeStatus.REJECTED.value, "accepted_at": None, "accepted_by": None,
                                       "reason": body.reason.strip() or "Rejected"})
    await _audit(repos, access, "take.reject", str(take_id), {"shot_id": str(take["shot_id"]), "reason": body.reason})
    return await _view(repos, access, UUID(str(take["shot_id"])))


# ── the bundle ─────────────────────────────────────────────────────────────────────────────


def _readme(ld: Loaded, rows: list[tuple[ShotState, list[Check]]]) -> str:
    scene = ld.scene
    out = [f"{ld.production.get('title') or 'Hiru production'} · Scene {scene['number']}: {scene.get('heading') or ''}",
           f"Aspect ratio {ld.aspect}. Made {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC.", "",
           "Each folder is one shot, in cut order: prompt.txt to paste into Flow, and first_frame.* to",
           "attach as its first frame. A shot that carries on from the previous take opens on that",
           "take's last frame instead.", ""]
    for st, checks in rows:
        join = st.row.get("camera_link") or "cut"
        opening = ("carries on from the previous take" if st.row.get("frame_strategy") == FrameStrategy.CARRY_LAST_FRAME
                   else "first frame attached" if st.accepted else "NO FIRST FRAME ACCEPTED")
        prompt = (f"prompt v{st.prompt['version']}" + (" (OUT OF DATE)" if st.prompt_reasons else "")
                  if st.prompt else "NO PROMPT YET")
        fails = [c.label for c in checks if c.tone == "fail"]
        out.append(f"{st.code}  {st.row['duration_s']} s  join: {join}  {opening}  {prompt}"
                   + (f"  CHECKS FAIL: {'; '.join(fails)}" if fails else ""))
    return "\n".join(out) + "\n"


@router.get("/scenes/{scene_id}/bundle")
async def scene_bundle(production_id: UUID, scene_id: UUID, access: CanHandoff, repos: ReposDep) -> Response:
    """Every shot's latest prompt and accepted opening frame, as one zip, with a README that says
    what is missing or out of date. Nothing is held back: the person decides what to send."""
    ld = await load(repos, access, scene_id)
    rows = [(st, handoff_checks(ld, st)) for st in ld.states]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("README.txt", _readme(ld, rows))
        manifest = []
        for st, checks in rows:
            entry: Row = {"shot": st.code, "duration_s": int(st.row["duration_s"]),
                          "join": st.row.get("camera_link") or "cut",
                          "opens_on": st.row.get("frame_strategy") or "generate",
                          "prompt_version": int(st.prompt["version"]) if st.prompt else None,
                          "prompt_out_of_date": bool(st.prompt_reasons), "checks_failing": blocking(checks)}
            if st.prompt:
                bundle.writestr(f"{st.code}/prompt.txt", str(st.prompt.get("prose") or ""))
            if st.accepted and st.accepted.get("storage_path"):
                path = str(st.accepted["storage_path"])
                try:
                    bundle.writestr(f"{st.code}/first_frame.{path.rsplit('.', 1)[-1]}",
                                    await repos.storage.download("frames", path))
                    entry["first_frame"] = True
                except Exception:
                    entry["first_frame"] = False
            manifest.append(entry)
        bundle.writestr("shots.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    await repos.audit.record(action="scene.bundle", entity="scene", entity_id=str(scene_id),
                             actor_user_id=access.user.id, production_id=production_id,
                             diff={"shots": len(rows)})
    name = f"scene-{ld.scene['number']:02d}-handoff.zip"
    return Response(content=buffer.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
