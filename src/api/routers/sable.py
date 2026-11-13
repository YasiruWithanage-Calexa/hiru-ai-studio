"""Sable, the production assistant chat (plan/2026-11-08 §4.1, Phase 6).

The turn runs in the `sable_chat` function. The API decides, from trusted data, everything the function may not decide
for itself: who is asking (Permission.USE_SABLE), whether they may accept a card (Permission.DIRECT), which thread
(their own: threads are per person, D3), and which scene is in view (inside this production). It stores the person's
message first, so a turn that fails still leaves the question in the thread.

    GET    …/sable                                 is Sable on
    GET    …/sable/threads                         the caller's threads, newest first
    POST   …/sable/threads                         a new, empty thread
    GET    …/sable/threads/{tid}                   the thread and its messages
    DELETE …/sable/threads/{tid}                   the thread and its messages
    GET    …/sable/mentions?q=&scene_id=           the @ picker's list (names only, no model)
    POST   …/sable/turn                            one turn, streamed (`contracts.sable.events`)
    POST   …/sable/messages/{mid}/cards/{i}/accept a staged change applied (no model), or a rule remembered
    POST   …/sable/messages/{mid}/cards/{i}/dismiss the card set aside

Nothing here sends a reply's record (`chat_turn_meta`), a tier, a model or a cost (rule 1).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.config import get_settings
from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos, Row
from api.services import director as director_service
from api.services import sable as sable_service
from api.services.ai import UsageContext, get_ai
from contracts.director import MessageKind
from contracts.roles import Permission
from contracts.sable.events import (
    MentionOption,
    SableMessage,
    SableThread,
    SableTurnPayload,
    SableTurnRequest,
)

router = APIRouter(prefix="/v1/productions/{production_id}/sable", tags=["sable"])
ReposDep = Annotated[Repos, Depends(get_repos)]
CanAsk = Annotated[ProductionAccess, Depends(require_permission(Permission.USE_SABLE))]
CanDirect = Annotated[ProductionAccess, Depends(require_permission(Permission.DIRECT))]
Streamer = Annotated[sable_service.SableStreamer, Depends(sable_service.get_streamer)]
Applier = Annotated[sable_service.SableActor, Depends(sable_service.get_actor)]  # a change card, carried out in code
BEFORE_ROWS = ("This card was made before Sable's change cards were updated, so it can't be applied. Ask Sable "
               "again.")
OFF = "Sable is switched off."


class SableStatus(BaseModel):
    enabled: bool
    can_accept: bool  # Permission.DIRECT: whether the caller's cards can be accepted (D8)


class ThreadCreate(BaseModel):
    title: str = Field("", max_length=120)


class ThreadView(BaseModel):
    thread: SableThread
    messages: list[SableMessage]


class CardResult(BaseModel):
    ok: bool
    text: str
    message: SableMessage


def _on() -> None:
    if not get_settings().sable.enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, OFF)


async def _own_thread(repos: Repos, access: ProductionAccess, thread_id: UUID) -> Row:
    """The caller's own Sable thread; another person's, or another chat's, is 404 (threads are per person, D3)."""
    thread = await repos.sable.thread(access.production_id, thread_id)
    if thread is None or str(thread.get("created_by")) != str(access.user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found.")
    return thread


@router.get("", response_model=SableStatus)
async def get_status(production_id: UUID, access: CanAsk) -> SableStatus:
    return SableStatus(enabled=get_settings().sable.enabled, can_accept=Permission.DIRECT in access.permissions)


@router.get("/threads", response_model=list[SableThread])
async def list_threads(production_id: UUID, access: CanAsk, repos: ReposDep) -> list[SableThread]:
    return [SableThread.model_validate(t) for t in await repos.sable.threads(production_id, access.user.id)]


@router.post("/threads", response_model=SableThread, status_code=status.HTTP_201_CREATED)
async def create_thread(production_id: UUID, body: ThreadCreate, access: CanAsk, repos: ReposDep) -> SableThread:
    _on()
    row = await repos.sable.create({"production_id": str(production_id), "title": body.title.strip() or "New chat",
                                    "created_by": str(access.user.id)})
    return SableThread.model_validate(row)


@router.get("/threads/{thread_id}", response_model=ThreadView)
async def get_thread(production_id: UUID, thread_id: UUID, access: CanAsk, repos: ReposDep) -> ThreadView:
    thread = await _own_thread(repos, access, thread_id)
    cache: dict[str, str] = {}
    rows = await repos.messages.list(thread_id)
    return ThreadView(thread=SableThread.model_validate(thread),
                      messages=[await sable_service.view(repos, production_id, m, cache) for m in rows])


@router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(production_id: UUID, thread_id: UUID, access: CanAsk, repos: ReposDep) -> None:
    await _own_thread(repos, access, thread_id)
    await repos.sable.delete(thread_id)
    await repos.audit.record(action="sable.delete_thread", entity="chat_thread", entity_id=str(thread_id),
                             actor_user_id=access.user.id, production_id=production_id)


@router.get("/mentions", response_model=list[MentionOption])
async def mentions(production_id: UUID, access: CanAsk, repos: ReposDep, q: str = "",
                   scene_id: UUID | None = None) -> list[MentionOption]:
    """The @ picker's list: the open scene's shots and blocks first, then the canon, then the other scenes. Names only,
    no model."""
    if scene_id is not None and await repos.scenes.get(production_id, scene_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scene not found.")
    return await sable_service.mention_options(repos, production_id, scene_id, q[:80])


@router.post("/turn")
async def turn(production_id: UUID, body: SableTurnRequest, access: CanAsk, repos: ReposDep,
               streamer: Streamer) -> StreamingResponse:
    """One Sable turn, streamed as server-sent events: first `accepted` {thread_id, message} with the stored message,
    then the function's frames."""
    _on()
    if body.scene_id is not None and await repos.scenes.get(production_id, body.scene_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scene not found.")
    text = body.message.strip()
    try:  # what @ pointed at is read again from this production: a thing that is not here is 404
        mentioned = await sable_service.resolve_refs(repos, production_id, body.scene_id, body.refs)
    except sable_service.UnknownRef as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{exc} was not found in this production.") from exc
    if body.thread_id is not None:
        thread = await _own_thread(repos, access, body.thread_id)
    else:
        thread = await repos.sable.create({"production_id": str(production_id),
                                           "title": sable_service.title_of(text), "created_by": str(access.user.id)})
    thread_id = UUID(str(thread["id"]))
    try:  # Edit / Ask again: the person's last message is replaced, never deleted
        blocks = await director_service.replaces_blocks(repos, thread_id, body.replaces, text)
    except director_service.NotReplaceable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    message = await repos.messages.create({
        "id": str(uuid4()), "production_id": str(production_id), "thread_id": str(thread_id),
        "kind": MessageKind.USER.value, "author_user_id": str(access.user.id), "speaker": access.user.display_name,
        "text": text, "blocks": blocks})
    await repos.threads.touch(thread_id)
    role = "admin" if access.role is None else str(access.role.value)
    payload = SableTurnPayload(production_id=production_id, thread_id=thread_id, actor_user_id=access.user.id,
                               actor_name=access.user.display_name, role=role,
                               can_stage=Permission.DIRECT in access.permissions, message=text,
                               user_message_id=UUID(str(message["id"])), scene_id=body.scene_id,
                               replaces=body.replaces, mentions=mentioned)
    accepted = (await sable_service.view(repos, production_id, message)).model_dump(mode="json")

    async def frames() -> AsyncIterator[bytes]:
        yield director_service.sse("accepted", {"thread_id": str(thread_id), "message": accepted})
        async for chunk in streamer(payload.model_dump(mode="json")):
            yield chunk

    return StreamingResponse(frames(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _card(repos: Repos, access: ProductionAccess, message_id: UUID, index: int) -> tuple[Row, Row]:
    row = await repos.messages.get(access.production_id, message_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found.")
    await _own_thread(repos, access, UUID(str(row["thread_id"])))
    card = sable_service.card_at(row, index)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card not found.")
    if card.get("status", "open") != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, "This card was already used.")
    return row, card


async def _settle(repos: Repos, access: ProductionAccess, row: Row, index: int, state: str, note: str,
                  text: str) -> CardResult:
    updated = await repos.messages.update(UUID(str(row["id"])), {"blocks": sable_service.with_status(
        row, index, state, note)})
    return CardResult(ok=state == "accepted" or state == "dismissed", text=text,
                      message=await sable_service.view(repos, access.production_id, updated))


@router.post("/messages/{message_id}/cards/{index}/accept", response_model=CardResult)
async def accept(production_id: UUID, message_id: UUID, index: int, access: CanDirect, repos: ReposDep,
                 applier: Applier, request: Request) -> CardResult:
    """A card is carried out by code, never a model: a change's row-kernel operations (stored when they were confirmed
    to land) are replayed in the function and saved in place as a revision (plan/2026-11-13 phase 8), refused if the
    shots changed since; a rule becomes a remembered decision of the production."""
    row, card = await _card(repos, access, message_id, index)
    if card["kind"] == "sable_change":
        scene_id = UUID(str(card["scene_id"]))
        scene = await repos.scenes.get(production_id, scene_id)
        if scene is None:
            return await _settle(repos, access, row, index, "failed", "The scene is gone.", "The scene is gone.")
        if scene.get("status") == "approved":
            raise HTTPException(status.HTTP_409_CONFLICT, "This scene is approved and locked. Unapprove it first.")
        if card.get("engine") != "rows":
            return await _settle(repos, access, row, index, "failed", BEFORE_ROWS, BEFORE_ROWS)
        out = await applier({"kind": "apply", "production_id": str(production_id), "scene_id": str(scene_id),
                             "actor_user_id": str(access.user.id), "message_id": str(message_id),
                             "ops": list(card.get("ops") or []), "made_on": str(card.get("made_on") or ""),
                             "summary": str(card.get("summary") or "")})
        text = str(out.get("text") or "")
        if not out.get("ok"):
            return await _settle(repos, access, row, index, "failed", text, text)
        await repos.audit.record(action="sable.accept_change", entity="scene", entity_id=str(scene_id),
                                 actor_user_id=access.user.id, production_id=production_id,
                                 diff={"message_id": str(message_id), "ops": len(card.get("ops") or []),
                                       "revision": int(out.get("revision") or 0)})
        return await _settle(repos, access, row, index, "accepted", "", text)
    if card["kind"] == "sable_state":
        scene_id = UUID(str(card["scene_id"]))
        scene = await repos.scenes.get(production_id, scene_id)
        if scene is None:
            return await _settle(repos, access, row, index, "failed", "The scene is gone.", "The scene is gone.")
        if scene.get("status") == "approved":
            raise HTTPException(status.HTTP_409_CONFLICT, "This scene is approved and locked. Unapprove it first.")
        try:
            changes, touched = await sable_service.apply_state_card(repos, production_id, scene, card)
        except sable_service.StateRefusedHere as exc:
            return await _settle(repos, access, row, index, "failed", str(exc), str(exc))
        await repos.audit.record(action="sable.accept_state", entity="scene", entity_id=str(scene_id),
                                 actor_user_id=access.user.id, production_id=production_id,
                                 diff={"message_id": str(message_id), "changes": changes, "shots": touched})
        text = "Applied: " + "; ".join(changes) + "." + sable_service.shot_words(touched)
        return await _settle(repos, access, row, index, "accepted", "", text.strip())
    rule = str(card.get("rule") or "").strip()
    scene_id_raw: Any = card.get("scene_id") if card.get("scope") == "scene" else None
    ai = get_ai(request)
    embedding = await ai.embed_query(rule, UsageContext(repos, access.user.id, production_id))
    item = await repos.memory.add({"id": str(uuid4()), "production_id": str(production_id),
                                   "scene_id": str(scene_id_raw) if scene_id_raw else None, "kind": "decision",
                                   "text": rule, "source_ref": {"by": "sable", "message_id": str(message_id)},
                                   "created_by": str(access.user.id)}, embedding, ai.settings.embedding_model)
    await repos.audit.record(action="memory.add", entity="memory_item", entity_id=str(item["id"]),
                             actor_user_id=access.user.id, production_id=production_id)
    return await _settle(repos, access, row, index, "accepted", "", "Remembered.")


@router.post("/messages/{message_id}/cards/{index}/dismiss", response_model=CardResult)
async def dismiss(production_id: UUID, message_id: UUID, index: int, access: CanAsk, repos: ReposDep) -> CardResult:
    row, _ = await _card(repos, access, message_id, index)
    return await _settle(repos, access, row, index, "dismissed", "", "Set aside.")
