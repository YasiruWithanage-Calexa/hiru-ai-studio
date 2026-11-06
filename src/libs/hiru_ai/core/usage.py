"""One `token_usage` row per model call, whatever the call (chat, streamed chat, tool round, embedding).

`UsageCallback` listens to LangChain: when a chat model call ends, it reads the token counts the provider
reported and hands one row to a sink. A sink that fails never fails the work it accounts for.

A row has exactly the columns the table has (`phase, model, input_tokens, cached_input_tokens, output_tokens`);
the composition root adds `job_id`, `production_id` and `actor_user_id` (`RunContext.usage_row`). With
`RunContext.usage_detail` (schema v10, plan/2026-11-04 §6.7) a row also says WHICH part made the call and what its tool
loop cost: `component`, `component_version`, `prompt_hash`, `tool_calls` (tool calls the model's answer asked for) and
`tool_result_tokens` (tokens of tool results sent to it); and, from schema v12 (plan/2026-11-05), `reasoning_tokens` (of
the output, the hidden reasoning a reasoning model bills as output). Without it a row is exactly the v9 row.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from hiru_ai.core.telemetry import logger

UsageRow = dict[str, Any]
UsageSink = Callable[[UsageRow], None]

_log = logger("usage")


def row(phase: str, model: str, input_tokens: int = 0, cached_input_tokens: int = 0,
        output_tokens: int = 0) -> UsageRow:
    return {"phase": phase, "model": model, "input_tokens": int(input_tokens),
            "cached_input_tokens": int(cached_input_tokens), "output_tokens": int(output_tokens)}


@dataclass(frozen=True)
class Detail:
    """Which part made the calls (the extra `token_usage` columns of schema v10)."""

    component: str = ""  # "agent:chat_answerer"
    version: int = 1
    prompt_hash: str = ""


def safely(sink: UsageSink | None, usage: UsageRow) -> None:
    """Hand a row to the sink; accounting must never fail the work it accounts for."""
    if sink is None:
        return
    try:
        sink(usage)
    except Exception:
        _log.warning("usage row not recorded phase=%s", usage.get("phase"), exc_info=True)


def tool_result_tokens(messages: Iterable[BaseMessage]) -> int:
    """Tokens of the tool results a model call was sent (what a loop pays again on every round)."""
    from hiru_ai.core.tooling import tokens_of

    return sum(tokens_of(m.content if isinstance(m.content, str) else str(m.content))
               for m in messages if isinstance(m, ToolMessage))


class UsageCallback(BaseCallbackHandler):
    """Attach to a chat model (`callbacks=[...]`) or to a call (`config={"callbacks": [...]}`)."""

    raise_error = False  # a bug here must not break a model call

    def __init__(self, sink: UsageSink | None, phase: str, default_model: str = "",
                 detail: Detail | None = None) -> None:
        self.sink = sink
        self.phase = phase
        self.default_model = default_model
        self.detail = detail
        self.rows: list[UsageRow] = []
        self._sent: dict[UUID, int] = {}  # run id of a call -> the tool result tokens it was sent

    def on_chat_model_start(self, serialized: dict[str, Any], messages: list[list[BaseMessage]], *,
                            run_id: UUID, **kwargs: Any) -> None:
        if self.detail is not None:
            self._sent[run_id] = sum(tool_result_tokens(batch) for batch in messages)

    def on_llm_end(self, response: LLMResult, *, run_id: UUID | None = None, **kwargs: Any) -> None:
        for generations in response.generations:
            for gen in generations:
                if not isinstance(gen, ChatGeneration):
                    continue
                meta = getattr(gen.message, "usage_metadata", None)
                if not meta:
                    continue
                details = meta.get("input_token_details") or {}
                model = (gen.message.response_metadata or {}).get("model_name") or self.default_model
                usage = row(self.phase, model, meta.get("input_tokens", 0), details.get("cache_read", 0) or 0,
                            meta.get("output_tokens", 0))
                if self.detail is not None:
                    usage |= {"component": self.detail.component, "component_version": self.detail.version,
                              "prompt_hash": self.detail.prompt_hash,
                              "reasoning_tokens": int((meta.get("output_token_details") or {}).get("reasoning") or 0),
                              "tool_calls": len(getattr(gen.message, "tool_calls", None) or []),
                              "tool_result_tokens": self._sent.pop(run_id, 0) if run_id else 0}
                self.rows.append(usage)
                safely(self.sink, usage)
