"""HTTP entry: payload → frame job. The echo template's contract: 400 for a malformed payload;
a crash marks the job failed and answers 200 (a re-delivery would pay for the pictures again);
500 only for a transient network error before any picture was asked for."""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

import httpx
from pydantic import ValidationError

from contracts.jobs import DispatchPayload
from frame_render.engine import image, pipeline
from frame_render.engine.inspect import Inspector
from frame_render.runtime.config import Config, get_config
from frame_render.runtime.jobs import Jobs
from frame_render.runtime.rest import Rest
from frame_render.runtime.store import Store

_logger = logging.getLogger(__name__)


def painter(config: Config, payload: DispatchPayload, store: Store, client: Any = None) -> pipeline.Painter | None:
    """The image tier as a function, with a `token_usage` row per picture. None without a key."""
    if client is None:
        if not config.images_enabled:
            return None
        from openai import OpenAI

        client = OpenAI(api_key=config.openai_api_key, timeout=240.0, max_retries=1)

    def paint(prompt: str, aspect: str, references: list[image.Reference], *, draft: bool = False) -> image.Picture:
        picture = image.generate(client, model=config.image_model,
                                 quality=config.image_quality_draft if draft else config.image_quality, prompt=prompt,
                                 aspect_ratio=aspect, references=references)
        store.record_usage({"job_id": str(payload.job_id), "production_id": str(payload.production_id),
                            "actor_user_id": str(payload.actor_user_id), "phase": "frame_render.image",
                            "model": config.image_model, "input_tokens": picture.input_tokens,
                            "cached_input_tokens": 0, "output_tokens": picture.output_tokens})
        return picture

    return paint


def inspector(config: Config, payload: DispatchPayload, store: Store, client: Any = None) -> Inspector | None:
    """The vision tier as a function (strict JSON), with a `token_usage` row per look. None without
    a key or when switched off (`OPENAI__MODEL_VISION=""`)."""
    if not config.vision_model:
        return None
    if client is None:
        if not config.images_enabled:
            return None
        from openai import OpenAI

        client = OpenAI(api_key=config.openai_api_key, timeout=120.0, max_retries=1)

    def look(data: bytes, mime: str, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
        resp = client.chat.completions.create(
            model=config.vision_model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": [{"type": "text", "text": user},
                                                   {"type": "image_url", "image_url": {"url": url, "detail": "low"}}]}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": "frame_check", "schema": schema, "strict": True}})
        usage = resp.usage
        store.record_usage({"job_id": str(payload.job_id), "production_id": str(payload.production_id),
                            "actor_user_id": str(payload.actor_user_id), "phase": "frame_render.vision",
                            "model": config.vision_model, "input_tokens": usage.prompt_tokens if usage else 0,
                            "cached_input_tokens": 0, "output_tokens": usage.completion_tokens if usage else 0})
        return dict(json.loads(resp.choices[0].message.content or "{}"))

    return look


def run_graph(payload: DispatchPayload, jobs: Jobs) -> dict[str, Any]:
    """The same job through the `hiru_ai` frame_render system (AI_ENGINE=graph): the thin handler builds the run's
    context with real adapters, the painter among them, and hands over. The vision check is an agent of the system."""
    from hiru_ai.adapters import supabase_rest
    from hiru_ai.systems.frame_render import graph

    return graph.run(payload, supabase_rest.build_context(payload, jobs=jobs, images=True))


def handle(request: Any) -> tuple[dict[str, Any], int]:
    try:
        payload = DispatchPayload.model_validate(request.get_json(silent=True) or {})
        if payload.production_id is None:
            raise ValueError("production_id is required")
    except (ValidationError, ValueError):
        return {"error": "bad payload"}, 400

    config = get_config()
    rest = Rest(config.supabase_url, config.service_role_key)
    store = Store(rest)
    jobs = Jobs(rest, config.api_internal_url, config.internal_secret)
    try:
        if os.environ.get("AI_ENGINE", "legacy") == "graph":
            return run_graph(payload, jobs), 200
        return pipeline.run(payload, store, jobs, painter(config, payload, store),
                            inspector(config, payload, store)), 200
    except httpx.TransportError:
        _logger.warning("transient network error job=%s", payload.job_id, exc_info=True)
        return {"error": "retry"}, 500
    except Exception:
        _logger.exception("frame_render failed job=%s", payload.job_id)
        jobs.fail(payload.job_id, "Making the frames failed.")
        return {"error": "failed"}, 200
