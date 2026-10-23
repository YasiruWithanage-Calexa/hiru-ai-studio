"""The one way this function calls OpenAI: tiers, structured JSON output, embeddings, and a
usage record for every call. `enabled` is False without a key; callers then skip the model."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from doc_ingest.runtime.config import Config

UsageSink = Callable[[dict[str, Any]], None]


class LLM:
    def __init__(self, config: Config, on_usage: UsageSink | None = None, client: Any = None) -> None:
        self.config = config
        self._on_usage = on_usage or (lambda row: None)
        self._client = client
        if self._client is None and config.llm_enabled:
            from openai import OpenAI

            self._client = OpenAI(api_key=config.openai_api_key, timeout=60.0, max_retries=2)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def _tier(self, tier: str) -> tuple[str, str]:
        if tier == "medium":
            return self.config.model_medium, self.config.effort_medium
        return self.config.model_low, self.config.effort_low

    def json(self, *, tier: str, phase: str, system: str, user: str,
             schema_name: str, schema: dict[str, Any]) -> dict[str, Any]:
        """A JSON object that matches `schema` (OpenAI structured outputs, strict)."""
        model, effort = self._tier(tier)
        kwargs: dict[str, Any] = {}
        if effort:
            kwargs["reasoning_effort"] = effort
        resp = self._client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": schema_name, "schema": schema, "strict": True}},
            **kwargs,
        )
        usage = resp.usage
        details = getattr(usage, "prompt_tokens_details", None)
        self._on_usage({"phase": phase, "model": model,
                        "input_tokens": usage.prompt_tokens if usage else 0,
                        "cached_input_tokens": getattr(details, "cached_tokens", 0) or 0,
                        "output_tokens": usage.completion_tokens if usage else 0})
        return json.loads(resp.choices[0].message.content or "{}")

    def asker(self, *, tier: str, phase: str, schema_name: str,
              schema: dict[str, Any]) -> Callable[[str, str], dict[str, Any]] | None:
        """(system, user) → dict, bound to one tier and schema; None when disabled."""
        if not self.enabled:
            return None
        return lambda system, user: self.json(tier=tier, phase=phase, system=system, user=user,
                                              schema_name=schema_name, schema=schema)

    def embed(self, texts: list[str], *, phase: str) -> list[list[float]]:
        model = self.config.embedding_model
        resp = self._client.embeddings.create(model=model, input=texts,
                                              dimensions=self.config.embedding_dimensions)
        self._on_usage({"phase": phase, "model": model,
                        "input_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                        "cached_input_tokens": 0, "output_tokens": 0})
        return [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]
