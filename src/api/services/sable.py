"""Sable's server side that is not a route (plan/2026-11-08 §4.6, §4.7): the proxy to the `sable_chat` function, what a
stored message shows (never its `meta`), where a handoff card goes, and how a card a person accepts is carried out.

Like Zora the function is internal: locally a functions-framework port; on Cloud Run the API calls it with a
Google-signed ID token. Frames are forwarded byte for byte; a failure becomes one `error` frame with a sentence for
the person.

Sable never imports Zora. The one thing it reads of Zora's is `zora.routes_here(scene)` (read-only, rule 10): whether a
scene's edits go to Zora or to the classic chat, so the handoff card opens the right composer.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx

from api.config import get_settings
from api.repositories import Repos, Row
from api.services import zora as scene_chats  # read-only: `routes_here` (rule 10)
from api.services.director import _id_token, sse
from api.workers import task_manager
from contracts.sable.events import UNAVAILABLE, SableMessage

_logger = logging.getLogger(__name__)
CARD_KINDS = ("sable_change", "sable_memory")
SableStreamer = Callable[[dict[str, Any]], AsyncIterator[bytes]]


async def _headers(url: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if not get_settings().local_functions:
        headers["Authorization"] = f"Bearer {await asyncio.to_thread(_id_token, url)}"
    return headers


async def stream_turn(payload: dict[str, Any]) -> AsyncIterator[bytes]:
    spec = task_manager.SABLE_CHAT
    url = task_manager.function_url(spec, get_settings())
    started = False
    try:
        headers = await _headers(url)
        timeout = httpx.Timeout(float(spec.deadline_s), connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client, client.stream(
                "POST", url, json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                _logger.warning("sable function answered %s thread=%s", resp.status_code, payload.get("thread_id"))
                yield sse("error", {"message": UNAVAILABLE})
                return
            async for chunk in resp.aiter_raw():
                started = True
                yield chunk
    except Exception:
        _logger.exception("sable stream failed thread=%s", payload.get("thread_id"))
        yield (b"\n\n" if started else b"") + sse("error", {"message": UNAVAILABLE})


def get_streamer() -> SableStreamer:
    """A dependency, so tests can stand in for the function."""
    return stream_turn


def title_of(message: str) -> str:
    """A new thread is titled from its first message: its first line, cut at a word, at most 60 characters."""
    first = (message.strip().splitlines() or [""])[0].strip()
    if len(first) <= 60:
        return first or "New chat"
    cut = first[:60].rsplit(" ", 1)[0]
    return f"{cut or first[:60]}…"


async def handoff_target(repos: Repos, production_id: Any, scene_id: Any, cache: dict[str, str]) -> str:
    """"zora" when the scene's edits go to Zora (`zora.routes_here`), "classic" otherwise; "" for a scene that
    is gone."""
    key = str(scene_id)
    if key not in cache:
        scene = await repos.scenes.get(production_id, scene_id)
        cache[key] = "" if scene is None else ("zora" if scene_chats.routes_here(scene) else "classic")
    return cache[key]


async def view(repos: Repos, production_id: Any, row: Row, cache: dict[str, str] | None = None) -> SableMessage:
    """A stored message as the panel reads it: never `meta` (rule 1); each handoff card says where it opens."""
    cache = {} if cache is None else cache
    blocks = []
    for block in row.get("blocks") or []:
        if isinstance(block, dict) and block.get("kind") == "handoff" and block.get("scene_id"):
            block = {**block, "target": await handoff_target(repos, production_id, block["scene_id"], cache)}
        blocks.append(block)
    shown = {k: v for k, v in row.items() if k != "meta"}
    return SableMessage.model_validate({**shown, "blocks": blocks})


def card_at(row: Row, index: int) -> Row | None:
    """The card a person acts on, by its place in the message's blocks; None when there is no such card."""
    blocks = row.get("blocks") or []
    if not (0 <= index < len(blocks)):
        return None
    block = blocks[index]
    return block if isinstance(block, dict) and block.get("kind") in CARD_KINDS else None


def with_status(row: Row, index: int, status: str, note: str = "") -> list[Row]:
    blocks = [dict(b) for b in row.get("blocks") or []]
    blocks[index] = {**blocks[index], "status": status, "note": note}
    return blocks
