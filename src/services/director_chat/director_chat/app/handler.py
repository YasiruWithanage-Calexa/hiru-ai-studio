"""`hiru-director-chat`: one synchronous, STREAMED director turn (server-sent events out).

Pattern from PromptMotion `nova_chat/app/handler.py` (commit 1d748dc): not a job. The API checks
who is asking, stores their message, and proxies this function's event stream straight back to
the browser. Events: status | delta | plan | message | done | error (contracts.director).

An error event carries a sentence for the person, never an exception's text (the API forwards
frames verbatim).
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from typing import Any

from pydantic import ValidationError

from contracts.director import ChoicePayload, TurnPayload
from director_chat.engine import choice, turn
from director_chat.runtime.config import get_config
from director_chat.runtime.llm import LLM
from director_chat.runtime.rest import Rest
from director_chat.runtime.store import Store

_logger = logging.getLogger(__name__)
CLIENT_ERROR = "Something went wrong on our side. Please try again in a moment."


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def handle_choice(body: dict[str, Any]) -> Any:
    """A director chose a side in a disagreement: plain JSON in and out, no model call."""
    try:
        req = ChoicePayload.model_validate(body)
    except ValidationError:
        return {"error": "bad payload"}, 400
    config = get_config()
    try:
        if os.environ.get("AI_ENGINE", "legacy") == "graph":
            result = run_graph_choice(req)
        else:
            result = choice.apply_choice(req, Store(Rest(config.supabase_url, config.service_role_key)))
    except Exception:
        _logger.exception("director choice failed scene=%s", req.scene_id)
        return {"error": CLIENT_ERROR}, 500
    return result.model_dump(mode="json"), 200


def run_graph_choice(req: ChoicePayload) -> Any:
    """A director's choice through the `hiru_ai` director_chat system (AI_ENGINE=graph): no model call, no job."""
    from hiru_ai.adapters import supabase_rest
    from hiru_ai.systems.director_chat import graph

    return graph.choose(req, supabase_rest.build_context(req, jobs=None))


def run_graph_turn(req: TurnPayload) -> Iterator[tuple[str, dict[str, Any]]]:
    """The same turn through the `hiru_ai` director_chat system: the same events, in the same order."""
    from hiru_ai.adapters import supabase_rest
    from hiru_ai.systems.director_chat import graph

    return graph.run(req, supabase_rest.build_context(req, jobs=None))


def stream(req: TurnPayload, store: Store, llm: LLM) -> Iterator[str]:
    try:
        events = run_graph_turn(req) if os.environ.get("AI_ENGINE", "legacy") == "graph" else turn.run(req, store, llm)
        for event, data in events:
            yield sse(event, data)
    except Exception:
        _logger.exception("director turn failed scene=%s", req.scene_id)
        yield sse("error", {"message": CLIENT_ERROR})


def handle(request: Any) -> Any:
    from flask import Response, stream_with_context

    body = request.get_json(silent=True) or {}
    if isinstance(body, dict) and body.get("kind") == "choice":
        return handle_choice(body)
    try:
        req = TurnPayload.model_validate(body)
    except ValidationError:
        return {"error": "bad payload"}, 400
    config = get_config()
    store = Store(Rest(config.supabase_url, config.service_role_key))

    def on_usage(row: dict[str, Any]) -> None:
        scene = {"scene_id": str(req.scene_id)} if req.scene_id and os.environ.get("USAGE_SCENE", "").lower() in (
            "1", "true", "yes") else {}  # schema v17 (plan/2026-11-06d): the scene this answer was about
        store.record_usage({**row, "production_id": str(req.production_id), "actor_user_id": str(req.actor_user_id),
                            **scene})

    llm = LLM(config, on_usage)
    return Response(stream_with_context(stream(req, store, llm)), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
