"""`hiru-sable-chat`: Sable, the production assistant chat (plan/2026-11-08 §4.1, Phase 5).

Like `hiru-zora-chat`, not a job: the API checks who is asking, stores their message and proxies this function's event
stream straight back to the browser (`contracts.sable.events`). Sable has no legacy engine: the function is a thin
handler that builds the run's context with the real adapters and hands over to the `sable_chat` system. An error event
carries a sentence for the person, never an exception's text. A body with `"action": true` is a change card's Accept
(`contracts.sable.events.SableAction`, plan/2026-11-13 phase 8): plain JSON in and out, no model.
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterator
from typing import Any

from pydantic import ValidationError

from contracts.sable.events import UNAVAILABLE, SableAction, SableTurnPayload

_logger = logging.getLogger(__name__)


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def run_turn(req: SableTurnPayload, stop: threading.Event) -> Iterator[tuple[str, dict[str, Any]]]:
    from hiru_ai.adapters import supabase_rest
    from hiru_ai.systems.sable.sable_chat import graph

    return graph.run(req, supabase_rest.build_context(req, jobs=None), stop)


def run_action(req: SableAction) -> dict[str, Any]:
    from hiru_ai.adapters import supabase_rest
    from hiru_ai.systems.sable.sable_chat import graph

    return graph.act(req, supabase_rest.build_context(req, jobs=None)).model_dump(mode="json")


def handle_action(body: dict[str, Any]) -> tuple[dict[str, Any], int]:
    try:
        req = SableAction.model_validate({k: v for k, v in body.items() if k != "action"})
    except ValidationError:
        return {"error": "bad payload"}, 400
    try:
        return run_action(req), 200
    except Exception:
        _logger.exception("sable action failed scene=%s", req.scene_id)
        return {"ok": False, "text": UNAVAILABLE}, 200


def finish(events: Iterator[Any], stop: threading.Event, thread_id: Any) -> None:
    """The person pressed Stop (or the connection dropped): nothing more can be written, but the rest of the turn runs
    so its reply is saved, marked stopped (plan/2026-11-07 Phase 2). Never raises."""
    stop.set()
    try:
        for _ in events:
            pass
    except Exception:
        _logger.exception("a stopped sable turn failed while finishing thread=%s", thread_id)


def stream(req: SableTurnPayload) -> Iterator[str]:
    stop = threading.Event()
    events: Iterator[tuple[str, dict[str, Any]]] = iter(())
    try:
        events = iter(run_turn(req, stop))
        for event, data in events:
            yield sse(event, data)
    except GeneratorExit:
        finish(events, stop, req.thread_id)
        raise
    except Exception:
        _logger.exception("sable turn failed thread=%s", req.thread_id)
        yield sse("error", {"message": UNAVAILABLE})


def handle(request: Any) -> Any:
    from flask import Response, stream_with_context

    body = request.get_json(silent=True) or {}
    if isinstance(body, dict) and body.get("action") is True:
        return handle_action(body)
    try:
        req = SableTurnPayload.model_validate(body)
    except ValidationError:
        return {"error": "bad payload"}, 400
    return Response(stream_with_context(stream(req)), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
