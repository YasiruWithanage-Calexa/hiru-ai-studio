"""`hiru-zora-chat`: Zora, the director chat on a scene's shot rows (plan/2026-11-06e §4.10; plan/2026-11-13).

Like `hiru-director-chat`, not a job: the API checks who is asking, stores their message and proxies this function's
event stream straight back to the browser (`contracts.zora.events`). A body with `"action": true` is a person's click
(accept or reject a card, use a proposal, undo, redo, lock, unlock): plain JSON in and out, no model.

Zora has no legacy engine: the function is a thin handler that builds the run's context with the real adapters and
hands over to the `zora_chat` system. An error event carries a sentence for the person, never an exception's text.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from pydantic import ValidationError

from contracts.director import TurnPayload
from contracts.zora.events import ZoraAction

_logger = logging.getLogger(__name__)
CLIENT_ERROR = "Something went wrong on our side. Please try again in a moment."


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def run_turn(req: TurnPayload) -> Iterator[tuple[str, dict[str, Any]]]:
    from hiru_ai.adapters import supabase_rest
    from hiru_ai.systems.zora.zora_chat import graph

    return graph.run(req, supabase_rest.build_context(req, jobs=None))


def run_action(req: ZoraAction) -> dict[str, Any]:
    from hiru_ai.adapters import supabase_rest
    from hiru_ai.systems.zora.zora_chat import graph

    return graph.act(req, supabase_rest.build_context(req, jobs=None)).model_dump(mode="json")


def finish(events: Iterator[Any], scene_id: Any) -> None:
    """The person pressed Stop (or the connection dropped): the server closed the response, so nothing more can be
    written. Run the rest of the turn anyway, so its saves land together: the plan, its revision and the reply message,
    never a plan edit without its message (plan/2026-11-07 Phase 2; `tests/zora/test_stop.py`). Never raises."""
    try:
        for _ in events:
            pass
    except Exception:
        _logger.exception("a stopped turn failed while finishing scene=%s", scene_id)


def stream(req: TurnPayload) -> Iterator[str]:
    events: Iterator[tuple[str, dict[str, Any]]] = iter(())
    try:
        events = iter(run_turn(req))
        for event, data in events:
            yield sse(event, data)
    except GeneratorExit:
        finish(events, req.scene_id)
        raise
    except Exception:
        _logger.exception("zora turn failed scene=%s", req.scene_id)
        yield sse("error", {"message": CLIENT_ERROR})


def handle_action(body: dict[str, Any]) -> tuple[dict[str, Any], int]:
    try:
        req = ZoraAction.model_validate({k: v for k, v in body.items() if k != "action"})
    except ValidationError:
        return {"error": "bad payload"}, 400
    try:
        return run_action(req), 200
    except Exception:
        _logger.exception("zora action failed scene=%s kind=%s", req.scene_id, req.kind)
        return {"ok": False, "text": CLIENT_ERROR}, 200


def handle(request: Any) -> Any:
    from flask import Response, stream_with_context

    body = request.get_json(silent=True) or {}
    if isinstance(body, dict) and body.get("action") is True:
        return handle_action(body)
    try:
        req = TurnPayload.model_validate(body)
    except ValidationError:
        return {"error": "bad payload"}, 400
    return Response(stream_with_context(stream(req)), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
