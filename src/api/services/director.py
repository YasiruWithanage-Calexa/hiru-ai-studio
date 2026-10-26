"""The Director panel's server side that is not a route: the board as people see it, and the
proxy to the `director_chat` function's event stream (PLAN.md §3: "Chat tokens stream over SSE
(API proxies the function's stream)").

The function is internal: locally it is a functions-framework port; on Cloud Run the API calls
it with a Google-signed ID token for the function's URL (the API's service account holds
`run.invoker`). Frames are forwarded byte for byte; a failure becomes one `error` frame with a
sentence for the person, never an exception's text.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx

from api.config import get_settings
from api.repositories import Repos, Row
from api.workers import task_manager
from contracts.director import BoardMember, ChoicePayload, ChoiceResult, Persona, Seat, TurnPayload

_logger = logging.getLogger(__name__)
DEFAULT_LEAD = "classic-teledrama"  # the lead a production has before anyone picks one
UNAVAILABLE = "The director is not available right now. Please try again in a moment."

TurnStreamer = Callable[[TurnPayload], AsyncIterator[bytes]]


def sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n".encode()


def persona(row: Row) -> Persona:
    return Persona.model_validate(row)


async def board(repos: Repos, production_id: Any) -> tuple[list[BoardMember], bool]:
    """→ (members, lead first; is it the default board?). An empty board shows the default lead,
    the persona the director turn falls back on, so the panel and the turn agree."""
    rows = await repos.board.list(production_id)
    members = [BoardMember(persona=persona(r["persona"]), seat=Seat(r["seat"])) for r in rows if r.get("persona")]
    if members:
        return sorted(members, key=lambda m: m.seat is not Seat.LEAD), False
    fallback = next((p for p in await repos.personas.list() if p["slug"] == DEFAULT_LEAD), None)
    return ([BoardMember(persona=persona(fallback), seat=Seat.LEAD)] if fallback else []), True


def _id_token(audience: str) -> str:
    from google.auth.transport.requests import Request  # lazily: not needed locally
    from google.oauth2 import id_token

    return str(id_token.fetch_id_token(Request(), audience))


async def stream_turn(payload: TurnPayload) -> AsyncIterator[bytes]:
    settings = get_settings()
    spec = task_manager.DIRECTOR_CHAT
    url = task_manager.function_url(spec, settings)
    headers = {"Content-Type": "application/json"}
    started = False
    try:
        if not settings.local_functions:
            headers["Authorization"] = f"Bearer {await asyncio.to_thread(_id_token, url)}"
        timeout = httpx.Timeout(float(spec.deadline_s), connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client, client.stream(
                "POST", url, json=payload.model_dump(mode="json"), headers=headers) as resp:
            if resp.status_code != 200:
                _logger.warning("director function answered %s scene=%s", resp.status_code, payload.scene_id)
                yield sse("error", {"message": UNAVAILABLE})
                return
            async for chunk in resp.aiter_raw():
                started = True
                yield chunk
    except Exception:
        _logger.exception("director stream failed scene=%s", payload.scene_id)
        # Close a frame cut off mid-way before the error frame, so the browser can parse it.
        yield (b"\n\n" if started else b"") + sse("error", {"message": UNAVAILABLE})


def get_turn_streamer() -> TurnStreamer:
    """A dependency, so tests can stand in for the function."""
    return stream_turn


ChoiceApplier = Callable[[ChoicePayload], Awaitable[ChoiceResult]]


class DirectorUnavailable(RuntimeError):
    """The function could not be reached or failed; the person is told to try again."""


async def apply_choice(payload: ChoicePayload) -> ChoiceResult:
    """Ask the `director_chat` function to apply a chosen side's edit (plain JSON, no stream)."""
    settings = get_settings()
    spec = task_manager.DIRECTOR_CHAT
    url = task_manager.function_url(spec, settings)
    headers = {"Content-Type": "application/json"}
    try:
        if not settings.local_functions:
            headers["Authorization"] = f"Bearer {await asyncio.to_thread(_id_token, url)}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            resp = await client.post(url, json=payload.model_dump(mode="json"), headers=headers)
        resp.raise_for_status()
        return ChoiceResult.model_validate(resp.json())
    except Exception as exc:
        _logger.exception("director choice failed scene=%s", payload.scene_id)
        raise DirectorUnavailable(UNAVAILABLE) from exc


def get_choice_applier() -> ChoiceApplier:
    """A dependency, so tests can stand in for the function."""
    return apply_choice
