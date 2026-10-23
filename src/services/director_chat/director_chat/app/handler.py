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
from collections.abc import Iterator
from typing import Any

from pydantic import ValidationError

from contracts.director import TurnPayload
from director_chat.engine import turn
from director_chat.runtime.config import get_config
from director_chat.runtime.llm import LLM
from director_chat.runtime.rest import Rest
from director_chat.runtime.store import Store

_logger = logging.getLogger(__name__)
CLIENT_ERROR = "Something went wrong on our side. Please try again in a moment."


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def stream(req: TurnPayload, store: Store, llm: LLM) -> Iterator[str]:
    try:
        for event, data in turn.run(req, store, llm):
            yield sse(event, data)
    except Exception:
        _logger.exception("director turn failed scene=%s", req.scene_id)
        yield sse("error", {"message": CLIENT_ERROR})


def handle(request: Any) -> Any:
    from flask import Response, stream_with_context

    try:
        req = TurnPayload.model_validate(request.get_json(silent=True) or {})
    except ValidationError:
        return {"error": "bad payload"}, 400
    config = get_config()
    store = Store(Rest(config.supabase_url, config.service_role_key))

    def on_usage(row: dict[str, Any]) -> None:
        store.record_usage({**row, "production_id": str(req.production_id), "actor_user_id": str(req.actor_user_id)})

    llm = LLM(config, on_usage)
    return Response(stream_with_context(stream(req, store, llm)), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
