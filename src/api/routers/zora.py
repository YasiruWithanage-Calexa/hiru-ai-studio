"""Zora, the director chat on a scene's shot rows (plan/2026-11-06e §4.10; plan/2026-11-13 §3.10).

The turn runs in the `zora_chat` function. The API decides, from trusted data, everything the function may not decide
for itself: who is asking, whether they may change the shots (Permission.DIRECT), which scene and thread, and whether
Zora is on (`ZORA__ENABLED`). Any scene with shot rows is editable, whoever planned it: Zora depends on no planner. It
stores the person's message first, so a turn that fails still leaves the question in the thread.

    GET  …/scenes/{id}/zora              is Zora on, can it undo or redo, the revisions, the person's locks
    POST …/scenes/{id}/zora/turn         one turn, streamed (`contracts.zora.events`)
    POST …/scenes/{id}/zora/accept | reject   a card's Accept or Reject (the change is code, no model)
    POST …/scenes/{id}/zora/undo | redo  a revision restored in code (no model)
    POST …/scenes/{id}/zora/lock | unlock   a field a person set: no model may write it
    POST …/scenes/{id}/zora/plan-shots   "Re-plan the scene": a job of the production's `shot_planner`
    POST …/messages/{id}/use             a proposal's operations applied (no model)
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.config import get_settings
from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos, Row
from api.services import director as director_service
from api.services import zora as zora_service
from api.workers import task_manager
from contracts.build import build_pipeline
from contracts.director import ChatMessage, MessageKind, TurnPayload, TurnRequest
from contracts.producer import PersonEdits
from contracts.production import ProductionSettings
from contracts.roles import Permission

router = APIRouter(prefix="/v1/productions/{production_id}", tags=["zora"])
ReposDep = Annotated[Repos, Depends(get_repos)]
CanView = Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))]
CanComment = Annotated[ProductionAccess, Depends(require_permission(Permission.COMMENT))]
CanDirect = Annotated[ProductionAccess, Depends(require_permission(Permission.DIRECT))]
Streamer = Annotated[zora_service.ZoraStreamer, Depends(zora_service.get_streamer)]
Actor = Annotated[zora_service.ZoraActor, Depends(zora_service.get_actor)]


class RevisionView(BaseModel):
    revision: int
    kind: str
    restores: int | None = None
    made_by: UUID | None = None
    message_id: UUID | None = None
    created_at: str = ""


class ZoraStatus(BaseModel):
    enabled: bool  # ZORA__ENABLED
    available: bool  # this scene is Zora's (Zora is on); False: the classic chat
    reason: str = ""  # why not, in a sentence
    undo_available: bool  # the database has the revisions table and this scene has revisions
    can_undo: bool = False
    can_redo: bool = False
    revisions: list[RevisionView] = Field(default_factory=list)
    locked: list[str] = Field(default_factory=list)  # "S03.size": fields a person set (no model writes them)
    settled: list[str] = Field(default_factory=list)  # kept for the panel; Zora has no treatment to settle
    sequences: list[str] = Field(default_factory=list)  # kept for the panel; the shot rows have no sequences


class ActionResult(BaseModel):
    ok: bool
    text: str
    revision: int = 0
    ops: dict[str, Any] = Field(default_factory=dict)
    gate: dict[str, Any] = Field(default_factory=dict)
    can_undo: bool = False
    can_redo: bool = False
    message: dict[str, Any] | None = None  # Zora's reply to the click, as stored in the thread


class CardRequest(BaseModel):
    message_id: UUID  # the director message that carries the card
    block: int = Field(ge=0)  # the card's index in its blocks


class LockRequest(BaseModel):
    path: str = Field(min_length=1, max_length=120)  # "S03.lens", "treatment.approach"


class UseRequest(BaseModel):
    block: int = Field(ge=0)
    option: int = Field(ge=0)


class PlanStarted(BaseModel):
    job_id: UUID


async def _scene(repos: Repos, production_id: UUID, scene_id: UUID) -> Row:
    scene = await repos.scenes.get(production_id, scene_id)
    if scene is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scene not found.")
    return scene


def _why_not(scene: Row) -> str:
    """Why Zora cannot take this scene ("" when she can). Any scene is hers, whoever planned it (plan/2026-11-13): she
    edits its shot rows."""
    if not zora_service.routes_here(scene):
        return "Zora is switched off on this server; use Sable to change this scene."
    return ""


def _zora_scene(scene: Row) -> Row:
    """The scene, if it is Zora's (409 with the reason when it is not)."""
    reason = _why_not(scene)
    if reason:
        raise HTTPException(status.HTTP_409_CONFLICT, reason)
    return scene


@router.get("/scenes/{scene_id}/zora", response_model=ZoraStatus)
async def get_status(production_id: UUID, scene_id: UUID, _: CanView, repos: ReposDep) -> ZoraStatus:
    scene = await _scene(repos, production_id, scene_id)
    rows = await repos.revisions.list(scene_id)
    can_undo, can_redo = zora_service.undo_redo(rows)
    shots = await repos.shots.list(production_id, scene_id)
    reason = _why_not(scene)
    return ZoraStatus(enabled=get_settings().zora.enabled, available=not reason, reason=reason,
                      undo_available=bool(rows), can_undo=can_undo, can_redo=can_redo,
                      revisions=[RevisionView.model_validate({**r, "created_at": str(r.get("created_at") or "")})
                                 for r in rows][-30:],
                      locked=locked_of(shots))


def locked_of(shots: list[Row]) -> list[str]:
    """The fields a person set, as "S03.size": the take (`duration_locked`) and `person_edits.zora_locks`."""
    out: list[str] = []
    for n, shot in enumerate(sorted(shots, key=lambda r: int(r.get("number") or 0)), start=1):
        keys = (["take_s"] if shot.get("duration_locked") else []) + PersonEdits.of(shot).zora_locks
        out += [f"S{n:02d}.{k}" for k in keys]
    return out


@router.post("/scenes/{scene_id}/zora/turn")
async def turn(production_id: UUID, scene_id: UUID, body: TurnRequest, access: CanComment, repos: ReposDep,
               streamer: Streamer) -> StreamingResponse:
    """One Zora turn, streamed as server-sent events: first `accepted` {thread_id, message} with the stored message,
    then the function's frames."""
    _zora_scene(await _scene(repos, production_id, scene_id))
    if body.thread_id is not None:
        thread = await repos.threads.get(production_id, body.thread_id)
        if thread is None or str(thread.get("scene_id")) != str(scene_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found.")
    else:  # the scene's main thread, shared with the classic chat
        threads = await repos.threads.list(production_id, scene_id)
        thread = threads[0] if threads else await repos.threads.create({
            "production_id": str(production_id), "scene_id": str(scene_id), "title": "Director",
            "created_by": str(access.user.id)})
    thread_id = UUID(str(thread["id"]))
    try:  # Edit / Ask again: the person's last message is replaced, never deleted
        blocks = await director_service.replaces_blocks(repos, thread_id, body.replaces, body.message.strip())
    except director_service.NotReplaceable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    message = await repos.messages.create({
        "id": str(uuid4()), "production_id": str(production_id), "thread_id": str(thread_id),
        "kind": MessageKind.USER.value, "author_user_id": str(access.user.id),
        "speaker": access.user.display_name, "text": body.message.strip(), "blocks": blocks})
    await repos.threads.touch(thread_id)
    payload = TurnPayload(production_id=production_id, scene_id=scene_id, thread_id=thread_id,
                          actor_user_id=access.user.id, actor_name=access.user.display_name,
                          can_edit=Permission.DIRECT in access.permissions,
                          can_edit_script=Permission.EDIT_SCRIPT in access.permissions, message=body.message.strip(),
                          user_message_id=UUID(str(message["id"])), replaces=body.replaces)
    accepted = ChatMessage.model_validate(message).model_dump(mode="json")

    async def frames() -> AsyncIterator[bytes]:
        yield director_service.sse("accepted", {"thread_id": str(thread_id), "message": accepted})
        async for chunk in streamer(payload.model_dump(mode="json")):
            yield chunk

    return StreamingResponse(frames(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _act(repos: Repos, access: ProductionAccess, actor: zora_service.ZoraActor, scene_id: UUID, kind: str,
               **more: Any) -> ActionResult:
    scene = _zora_scene(await _scene(repos, access.production_id, scene_id))
    if scene.get("status") == "approved":
        raise HTTPException(status.HTTP_409_CONFLICT, "This scene is approved and locked. Unapprove it first.")
    out = await actor({"kind": kind, "production_id": str(access.production_id), "scene_id": str(scene_id),
                       "actor_user_id": str(access.user.id), "actor_name": access.user.display_name,
                       "can_edit": Permission.DIRECT in access.permissions, **more})
    result = ActionResult.model_validate(out)
    if result.ok:
        detail = {k: v for k, v in more.items() if k != "thread_id"}
        await repos.audit.record(action=f"scene.zora_{kind}", entity="scene", entity_id=str(scene_id),
                                 actor_user_id=access.user.id, production_id=access.production_id,
                                 diff={"revision": result.revision, **detail})
    return result


@router.post("/scenes/{scene_id}/zora/accept", response_model=ActionResult)
async def accept(production_id: UUID, scene_id: UUID, body: CardRequest, access: CanDirect, repos: ReposDep,
                 actor: Actor) -> ActionResult:
    """A card's Accept: its operations replayed in code in the batches they landed in, checked and saved (a revision);
    refused when the shots changed since the card was made."""
    thread_id = await _card_thread(repos, production_id, scene_id, body.message_id)
    return await _act(repos, access, actor, scene_id, "accept", message_id=str(body.message_id), block=body.block,
                      thread_id=thread_id)


@router.post("/scenes/{scene_id}/zora/reject", response_model=ActionResult)
async def reject(production_id: UUID, scene_id: UUID, body: CardRequest, access: CanDirect, repos: ReposDep,
                 actor: Actor) -> ActionResult:
    """A card's Reject: nothing changes, and Zora does not offer it again in this thread."""
    thread_id = await _card_thread(repos, production_id, scene_id, body.message_id)
    return await _act(repos, access, actor, scene_id, "reject", message_id=str(body.message_id), block=body.block,
                      thread_id=thread_id)


async def _card_thread(repos: Repos, production_id: UUID, scene_id: UUID, message_id: UUID) -> str:
    """The thread of the message that carries a card, which must be this scene's (404 otherwise)."""
    row = await repos.messages.get(production_id, message_id)
    thread = await repos.threads.get(production_id, UUID(str(row["thread_id"]))) if row else None
    if row is None or thread is None or str(thread.get("scene_id")) != str(scene_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found.")
    return str(thread["id"])


@router.post("/scenes/{scene_id}/zora/undo", response_model=ActionResult)
async def undo(production_id: UUID, scene_id: UUID, access: CanDirect, repos: ReposDep, actor: Actor) -> ActionResult:
    return await _act(repos, access, actor, scene_id, "undo")


@router.post("/scenes/{scene_id}/zora/redo", response_model=ActionResult)
async def redo(production_id: UUID, scene_id: UUID, access: CanDirect, repos: ReposDep, actor: Actor) -> ActionResult:
    return await _act(repos, access, actor, scene_id, "redo")


@router.post("/scenes/{scene_id}/zora/lock", response_model=ActionResult)
async def lock(production_id: UUID, scene_id: UUID, body: LockRequest, access: CanDirect, repos: ReposDep,
               actor: Actor) -> ActionResult:
    return await _act(repos, access, actor, scene_id, "lock", path=body.path)


@router.post("/scenes/{scene_id}/zora/unlock", response_model=ActionResult)
async def unlock(production_id: UUID, scene_id: UUID, body: LockRequest, access: CanDirect, repos: ReposDep,
                 actor: Actor) -> ActionResult:
    return await _act(repos, access, actor, scene_id, "unlock", path=body.path)


@router.post("/messages/{message_id}/use", response_model=ActionResult)
async def use(production_id: UUID, message_id: UUID, body: UseRequest, access: CanDirect, repos: ReposDep,
              actor: Actor) -> ActionResult:
    """A proposal's operations, applied with no model: they were tried on a copy and passed the planner's checks when
    they were offered, and the function refuses them if the plan changed since."""
    row = await repos.messages.get(production_id, message_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found.")
    thread = await repos.threads.get(production_id, UUID(str(row["thread_id"])))
    if thread is None or not thread.get("scene_id"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found.")
    return await _act(repos, access, actor, UUID(str(thread["scene_id"])), "use", message_id=str(message_id),
                      block=body.block, option=body.option, thread_id=str(thread["id"]))


@router.post("/scenes/{scene_id}/zora/plan-shots", response_model=PlanStarted, status_code=status.HTTP_202_ACCEPTED)
async def plan_shots(production_id: UUID, scene_id: UUID, access: CanDirect, repos: ReposDep) -> PlanStarted:
    """"Re-plan the scene" (plan/2026-11-13 §3.10, D-E): a job of the production's `shot_planner` setting (as the build
    chooses one), for this scene only. Zora plans nothing itself and names no planner."""
    scene = _zora_scene(await _scene(repos, production_id, scene_id))
    if scene.get("status") == "approved":
        raise HTTPException(status.HTTP_409_CONFLICT, "This scene is approved and locked. Unapprove it first.")
    if not scene.get("script"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This scene has no script to plan shots from.")
    planner = ProductionSettings.model_validate(access.production.get("settings") or {}).shot_planner
    kind = build_pipeline(planner)[-1]  # the job that plans a scene's shots
    job_id = await task_manager.dispatch(kind, repos, actor_user_id=access.user.id, production_id=production_id,
                                         request={"scene_id": str(scene_id)},
                                         state={"scene_ids": [str(scene_id)], "replan": True})
    await repos.audit.record(action="scene.zora_plan_shots", entity="scene", entity_id=str(scene_id),
                             actor_user_id=access.user.id, production_id=production_id, diff={"job_id": str(job_id)})
    return PlanStarted(job_id=job_id)
