"""The one way this function calls OpenAI: tiers, strict JSON output, tool calls, streamed text
and embeddings, each with a usage record. `enabled` is False without a key; the turn then runs
its rule-based path. Structured output is never combined with tools on one call (PromptMotion's
rule): a node either returns data or uses tools."""
from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

from director_chat.runtime.config import Config

UsageSink = Callable[[dict[str, Any]], None]


class LLM:
    def __init__(self, config: Config, on_usage: UsageSink | None = None, client: Any = None) -> None:
        self.config = config
        self._on_usage = on_usage or (lambda row: None)
        self._client = client
        if self._client is None and config.llm_enabled:
            from openai import OpenAI

            self._client = OpenAI(api_key=config.openai_api_key, timeout=120.0, max_retries=2)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def _kwargs(self, tier: str) -> tuple[str, dict[str, Any]]:
        t = self.config.tiers[tier]
        return t.model, ({"reasoning_effort": t.effort} if t.effort else {})

    def _record(self, phase: str, model: str, usage: Any) -> None:
        details = getattr(usage, "prompt_tokens_details", None)
        self._on_usage({"phase": phase, "model": model,
                        "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                        "cached_input_tokens": getattr(details, "cached_tokens", 0) or 0,
                        "output_tokens": getattr(usage, "completion_tokens", 0) or 0})

    def json(self, *, tier: str, phase: str, system: str, user: str,
             schema_name: str, schema: dict[str, Any]) -> dict[str, Any]:
        model, kw = self._kwargs(tier)
        resp = self._client.chat.completions.create(
            model=model, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_schema", "json_schema": {"name": schema_name, "schema": schema,
                                                                    "strict": True}}, **kw)
        self._record(phase, model, resp.usage)
        return json.loads(resp.choices[0].message.content or "{}")

    def tool_round(self, *, tier: str, phase: str, messages: list[dict[str, Any]],
                   tools: list[dict[str, Any]]) -> Any:
        """One call that may ask for tools. Returns the assistant message."""
        model, kw = self._kwargs(tier)
        resp = self._client.chat.completions.create(model=model, messages=messages, tools=tools, **kw)
        self._record(phase, model, resp.usage)
        return resp.choices[0].message

    def stream(self, *, tier: str, phase: str, messages: list[dict[str, Any]]) -> Iterator[str]:
        model, kw = self._kwargs(tier)
        chunks = self._client.chat.completions.create(model=model, messages=messages, stream=True,
                                                      stream_options={"include_usage": True}, **kw)
        for chunk in chunks:
            if getattr(chunk, "usage", None):
                self._record(phase, model, chunk.usage)
            for choice in chunk.choices or []:
                text = getattr(choice.delta, "content", None)
                if text:
                    yield text

    def embed(self, texts: list[str], *, phase: str) -> list[list[float]]:
        model = self.config.embedding_model
        resp = self._client.embeddings.create(model=model, input=texts, dimensions=self.config.embedding_dimensions)
        self._on_usage({"phase": phase, "model": model, "input_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                        "cached_input_tokens": 0, "output_tokens": 0})
        return [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]
