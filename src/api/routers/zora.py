"""Zora, the director chat over Shot Planner Jonathan's plan (plan/2026-11-06e §4.10, Phase 7).

The turn runs in the `zora_chat` function. The API decides, from trusted data, everything the function may not decide
for itself: who is asking, whether they may change the plan (Permission.DIRECT), which scene and thread, and whether
the scene is Zora's at all (`ZORA__ENABLED` and a stored Jonathan plan; any other scene keeps the classic chat). It
stores the person's message first, so a turn that fails still leaves the question in the thread.

    GET  …/scenes/{id}/zora              is this scene Zora's, can it undo or redo, the revisions
    POST …/scenes/{id}/zora/turn         one turn, streamed (`contracts.zora.events`)
    POST …/scenes/{id}/zora/undo | redo  a revision restored in code (no model)
    POST …/scenes/{id}/zora/lock | unlock   a field a person set: no model may write it
    POST …/scenes/{id}/zora/plan-shots   "Plan shots from this treatment": a Jonathan job with the treatment pinned
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
from contracts.director import ChatMessage, MessageKind, TurnPayload, TurnRequest
from contracts.jobs import JobKind
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
    available: bool  # this scene is Zora's (enabled and Jonathan planned it); False: the classic chat
    reason: str = ""  # why not, in a sentence
    undo_available: bool  # the database has the revisions table and this scene has revisions
    can_undo: bool = False
    can_redo: bool = False
    revisions: list[RevisionView] = Field(default_factory=list)
    locked: list[str] = Field(default_factory=list)
    settled: list[str] = Field(default_factory=list)
    sequences: list[str] = Field(default_factory=list)  # the plan's sequence ids, for "@" in the composer


class ActionResult(BaseModel):
    ok: bool
    text: str
    revision: int = 0
    ops: dict[str, Any] = Field(default_factory=dict)
    gate: dict[str, Any] = Field(default_factory=dict)
    can_undo: bool = False
    can_redo: bool = False


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
    if not get_settings().zora.enabled:
        return "Zora is switched off; the classic director chat edits this scene."
    if not zora_service.has_plan(scene):
        return "Zora edits a scene Shot Planner Jonathan has planned. Plan it with Jonathan first."
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
    stored = scene.get(zora_service.PLANNER) or {}
    person = stored.get("person") or {}
    sequences = [str(q.get("id")) for q in (stored.get("plan") or {}).get("sequences") or [] if q.get("id")]
    reason = _why_not(scene)
    return ZoraStatus(enabled=get_settings().zora.enabled, available=not reason, reason=reason,
                      undo_available=bool(rows), can_undo=can_undo, can_redo=can_redo,
                      revisions=[RevisionView.model_validate({**r, "created_at": str(r.get("created_at") or "")})
                                 for r in rows][-30:],
                      locked=list(person.get("locked") or []), settled=list(person.get("settled") or []),
                      sequences=sequences)


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
    message = await repos.messages.create({
        "id": str(uuid4()), "production_id": str(production_id), "thread_id": str(thread_id),
        "kind": MessageKind.USER.value, "author_user_id": str(access.user.id),
        "speaker": access.user.display_name, "text": body.message.strip()})
    await repos.threads.touch(thread_id)
    payload = TurnPayload(production_id=production_id, scene_id=scene_id, thread_id=thread_id,
                          actor_user_id=access.user.id, actor_name=access.user.display_name,
                          can_edit=Permission.DIRECT in access.permissions,
                          can_edit_script=Permission.EDIT_SCRIPT in access.permissions, message=body.message.strip(),
                          user_message_id=UUID(str(message["id"])))
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
    """"Plan shots from this treatment" (plan §4.9, D5): Shot Planner Jonathan plans the scene's shots with the
    treatment as it stands PINNED: its pack prints it as fixed and its check reports a plan that drifts from it."""
    scene = _zora_scene(await _scene(repos, production_id, scene_id))
    if scene.get("status") == "approved":
        raise HTTPException(status.HTTP_409_CONFLICT, "This scene is approved and locked. Unapprove it first.")
    treatment = dict((scene[zora_service.PLANNER].get("plan") or {}).get("treatment") or {})
    job_id = await task_manager.dispatch(JobKind.PLAN_SCENE_JONATHAN, repos, actor_user_id=access.user.id,
                                         production_id=production_id, request={"scene_id": str(scene_id)},
                                         state={"scene_ids": [str(scene_id)], "replan": True,
                                                "pinned": {str(scene_id): treatment}})
    await repos.audit.record(action="scene.zora_plan_shots", entity="scene", entity_id=str(scene_id),
                             actor_user_id=access.user.id, production_id=production_id, diff={"job_id": str(job_id)})
    return PlanStarted(job_id=job_id)
