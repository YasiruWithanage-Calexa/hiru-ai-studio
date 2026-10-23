"""The one way this function calls OpenAI: tiers, strict JSON-schema output, and a usage record
for every call. `enabled` is False without a key; callers then take their rule-based path."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from structure_build.runtime.config import Config

UsageSink = Callable[[dict[str, Any]], None]


class LLM:
    def __init__(self, config: Config, on_usage: UsageSink | None = None, client: Any = None) -> None:
        self.config = config
        self._on_usage = on_usage or (lambda row: None)
        self._client = client
        if self._client is None and config.llm_enabled:
            from openai import OpenAI

            self._client = OpenAI(api_key=config.openai_api_key, timeout=180.0, max_retries=2)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def json(self, *, tier: str, phase: str, system: str, user: str,
             schema_name: str, schema: dict[str, Any]) -> dict[str, Any]:
        """A JSON object that matches `schema` (OpenAI structured outputs, strict)."""
        t = self.config.tiers[tier]
        kwargs: dict[str, Any] = {"reasoning_effort": t.effort} if t.effort else {}
        resp = self._client.chat.completions.create(
            model=t.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": schema_name, "schema": schema, "strict": True}},
            **kwargs,
        )
        usage = resp.usage
        details = getattr(usage, "prompt_tokens_details", None)
        self._on_usage({"phase": phase, "model": t.model,
                        "input_tokens": usage.prompt_tokens if usage else 0,
                        "cached_input_tokens": getattr(details, "cached_tokens", 0) or 0,
                        "output_tokens": usage.completion_tokens if usage else 0})
        return json.loads(resp.choices[0].message.content or "{}")
