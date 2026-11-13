"""Zora's server side that is not a route (plan/2026-11-06e §4.10): which scenes Zora edits, the proxy to the
`zora_chat` function (a streamed turn, or an action as plain JSON), and what the revisions allow.

Like the classic director chat the function is internal: locally a functions-framework port; on Cloud Run the API calls
it with a Google-signed ID token. Frames are forwarded byte for byte; a failure becomes one `error` frame (or a refused
action) with a sentence for the person, never an exception's text.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx

from api.config import get_settings
from api.repositories import Row
from api.services.director import _id_token, sse
from api.workers import task_manager

_logger = logging.getLogger(__name__)
UNAVAILABLE = "Zora is not available right now. Please try again in a moment."

ZoraStreamer = Callable[[dict[str, Any]], AsyncIterator[bytes]]
ZoraActor = Callable[[dict[str, Any]], Awaitable[Row]]


def routes_here(scene: Row) -> bool:
    """Every scene goes to Zora when `ZORA__ENABLED`: she edits its shot rows, whoever planned them (plan/2026-11-13).
    `scene` stays in the signature: Sable asks per scene (`api.services.sable`)."""
    del scene
    return get_settings().zora.enabled


def undo_redo(rows: list[Row]) -> tuple[bool, bool]:
    """→ (can undo, can redo) from the scene's revisions, oldest first. The same replay as the function's
    (`zora_save.logic.Stack`; `tests/zora/test_api.py` holds the two to the same answers)."""
    done: list[int] = []
    undone: list[int] = []
    for r in sorted(rows, key=lambda r: int(r["revision"])):
        n, kind = int(r["revision"]), str(r.get("kind") or "turn")
        if kind in ("turn", "use", "base") or not done:
            done.append(n)
            undone = []
        elif kind == "undo" and len(done) > 1:
            undone.append(done.pop())
        elif kind == "redo" and undone:
            done.append(undone.pop())
    return len(done) > 1, bool(undone)


async def _headers(url: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if not get_settings().local_functions:
        headers["Authorization"] = f"Bearer {await asyncio.to_thread(_id_token, url)}"
    return headers


async def stream_turn(payload: dict[str, Any]) -> AsyncIterator[bytes]:
    spec = task_manager.ZORA_CHAT
    url = task_manager.function_url(spec, get_settings())
    started = False
    try:
        headers = await _headers(url)
        timeout = httpx.Timeout(float(spec.deadline_s), connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client, client.stream(
                "POST", url, json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                _logger.warning("zora function answered %s scene=%s", resp.status_code, payload.get("scene_id"))
                yield sse("error", {"message": UNAVAILABLE})
                return
            async for chunk in resp.aiter_raw():
                started = True
                yield chunk
    except Exception:
        _logger.exception("zora stream failed scene=%s", payload.get("scene_id"))
        yield (b"\n\n" if started else b"") + sse("error", {"message": UNAVAILABLE})


async def act(payload: dict[str, Any]) -> Row:
    """An action (accept, reject, use, undo, redo, lock, unlock) through the function: `ZoraActionResult` as JSON. A
    function that
    cannot be reached answers a refused action, never an error page."""
    spec = task_manager.ZORA_CHAT
    url = task_manager.function_url(spec, get_settings())
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            resp = await client.post(url, json={**payload, "action": True}, headers=await _headers(url))
        resp.raise_for_status()
        return dict(resp.json())
    except Exception:
        _logger.exception("zora action failed scene=%s", payload.get("scene_id"))
        return {"ok": False, "text": UNAVAILABLE}


def get_streamer() -> ZoraStreamer:
    """A dependency, so tests can stand in for the function."""
    return stream_turn


def get_actor() -> ZoraActor:
    return act
