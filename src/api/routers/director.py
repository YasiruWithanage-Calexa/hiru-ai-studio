"""The director's side of screen 2d: personas, the production's director board, chat threads and
the streamed turn, and production memory (PLAN.md §6, §10).

The turn itself runs in the `director_chat` function. The API decides everything the function
may not decide for itself, from trusted data: who is asking, whether they may change the shot
list (Permission.DIRECT), which scene, which thread. It stores the person's message first, so a
turn that fails still leaves the question in the thread.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.deps.auth import User
from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos
from api.services import director as director_service
from api.services.ai import UsageContext, get_ai
from contracts.director import (
    BoardMember,
    BoardUpdate,
    ChatMessage,
    ChatThread,
    MemoryCreate,
    MemoryItem,
    MessageKind,
    Persona,
    TurnPayload,
    TurnRequest,
)
from contracts.roles import Permission

router = APIRouter(tags=["director"])
ReposDep = Annotated[Repos, Depends(get_repos)]
CanView = Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))]
CanComment = Annotated[ProductionAccess, Depends(require_permission(Permission.COMMENT))]
CanDirect = Annotated[ProductionAccess, Depends(require_permission(Permission.DIRECT))]
Streamer = Annotated[director_service.TurnStreamer, Depends(director_service.get_turn_streamer)]
P = "/v1/productions/{production_id}"


class BoardView(BaseModel):
    members: list[BoardMember]  # the lead first
    is_default: bool  # nobody has picked a board yet; this is the lead the director uses


class ThreadCreate(BaseModel):
    title: str = Field(default="", max_length=200)


async def _scene(repos: Repos, production_id: UUID, scene_id: UUID) -> None:
    if await repos.scenes.get(production_id, scene_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scene not found.")


# ── personas and the board ─────────────────────────────────────────────────────────────────


@router.get("/v1/director-personas", response_model=list[Persona])
async def list_personas(_: User, repos: ReposDep) -> list[Persona]:
    return [director_service.persona(r) for r in await repos.personas.list()]


@router.get(P + "/director-board", response_model=BoardView)
async def get_board(production_id: UUID, _: CanView, repos: ReposDep) -> BoardView:
    members, default = await director_service.board(repos, production_id)
    return BoardView(members=members, is_default=default)


@router.put(P + "/director-board", response_model=BoardView)
async def set_board(production_id: UUID, body: BoardUpdate, access: CanDirect, repos: ReposDep) -> BoardView:
    found = {str(p["id"]): p for p in await repos.personas.get_many([s.persona_id for s in body.seats])}
    if any(str(s.persona_id) not in found or not found[str(s.persona_id)].get("active") for s in body.seats):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "One of those directors is not in the library.")
    await repos.board.replace(production_id, [s.model_dump() for s in body.seats], access.user.id)
    await repos.audit.record(action="board.update", entity="production", entity_id=str(production_id),
                             actor_user_id=access.user.id, production_id=production_id,
                             diff={"seats": [{"persona": found[str(s.persona_id)]["slug"], "seat": s.seat.value}
                                             for s in body.seats]})
    members, default = await director_service.board(repos, production_id)
    return BoardView(members=members, is_default=default)


# ── threads and messages ───────────────────────────────────────────────────────────────────


@router.get(P + "/scenes/{scene_id}/threads", response_model=list[ChatThread])
async def list_threads(production_id: UUID, scene_id: UUID, _: CanView, repos: ReposDep) -> list[ChatThread]:
    await _scene(repos, production_id, scene_id)
    return [ChatThread.model_validate(t) for t in await repos.threads.list(production_id, scene_id)]


@router.post(P + "/scenes/{scene_id}/threads", response_model=ChatThread, status_code=status.HTTP_201_CREATED)
async def create_thread(production_id: UUID, scene_id: UUID, body: ThreadCreate, access: CanComment,
                        repos: ReposDep) -> ChatThread:
    await _scene(repos, production_id, scene_id)
    row = await repos.threads.create({"production_id": str(production_id), "scene_id": str(scene_id),
                                      "title": body.title.strip(), "created_by": str(access.user.id)})
    return ChatThread.model_validate(row)


@router.get(P + "/threads/{thread_id}/messages", response_model=list[ChatMessage])
async def list_messages(production_id: UUID, thread_id: UUID, _: CanView, repos: ReposDep) -> list[ChatMessage]:
    if await repos.threads.get(production_id, thread_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found.")
    return [ChatMessage.model_validate(m) for m in await repos.messages.list(thread_id)]


# ── the turn ───────────────────────────────────────────────────────────────────────────────


@router.post(P + "/scenes/{scene_id}/chat")
async def chat(production_id: UUID, scene_id: UUID, body: TurnRequest, access: CanComment, repos: ReposDep,
               streamer: Streamer) -> StreamingResponse:
    """One director turn, streamed as server-sent events (`contracts.director`): first
    `accepted` {thread_id, message} with the stored message, then the function's frames."""
    await _scene(repos, production_id, scene_id)
    if body.thread_id is not None:
        thread = await repos.threads.get(production_id, body.thread_id)
        if thread is None or str(thread.get("scene_id")) != str(scene_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found.")
    else:  # the scene's main thread: its first, made on first use
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
                          can_edit=Permission.DIRECT in access.permissions, message=body.message.strip(),
                          user_message_id=UUID(str(message["id"])))
    accepted = ChatMessage.model_validate(message).model_dump(mode="json")

    async def frames() -> AsyncIterator[bytes]:
        yield director_service.sse("accepted", {"thread_id": str(thread_id), "message": accepted})
        async for chunk in streamer(payload):
            yield chunk

    return StreamingResponse(frames(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── production memory ──────────────────────────────────────────────────────────────────────


@router.get(P + "/memory", response_model=list[MemoryItem])
async def list_memory(production_id: UUID, _: CanView, repos: ReposDep,
                      scene_id: UUID | None = None) -> list[MemoryItem]:
    return [MemoryItem.model_validate(m) for m in await repos.memory.list(production_id, scene_id)]


@router.post(P + "/memory", response_model=MemoryItem, status_code=status.HTTP_201_CREATED)
async def add_memory(production_id: UUID, body: MemoryCreate, access: CanDirect, repos: ReposDep,
                     request: Request) -> MemoryItem:
    if body.scene_id is not None:
        await _scene(repos, production_id, body.scene_id)
    ai = get_ai(request)
    text = body.text.strip()
    embedding = await ai.embed_query(text, UsageContext(repos, access.user.id, production_id))
    row = await repos.memory.add({"id": str(uuid4()), "production_id": str(production_id),
                                  "scene_id": str(body.scene_id) if body.scene_id else None, "kind": body.kind,
                                  "text": text, "source_ref": {"by": "person"}, "created_by": str(access.user.id)},
                                 embedding, ai.settings.embedding_model)
    await repos.audit.record(action="memory.add", entity="memory_item", entity_id=str(row["id"]),
                             actor_user_id=access.user.id, production_id=production_id)
    return MemoryItem.model_validate(row)


@router.delete(P + "/memory/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(production_id: UUID, item_id: UUID, access: CanDirect, repos: ReposDep) -> None:
    row = await repos.memory.get(production_id, item_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    await repos.memory.delete(item_id)
    await repos.audit.record(action="memory.delete", entity="memory_item", entity_id=str(item_id),
                             actor_user_id=access.user.id, production_id=production_id, diff={"text": row["text"]})
