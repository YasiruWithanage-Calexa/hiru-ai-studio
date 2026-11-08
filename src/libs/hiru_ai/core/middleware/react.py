"""Middleware for `react` agents (a LangChain `create_agent` tool loop).

These are LangChain `AgentMiddleware`, because they wrap the steps inside the loop (a tool call, a model turn) that the
call-level middleware in this package cannot see. A `structured` agent is one call, so it gets its retries and fallback
tiers from the model door (`models.yaml`) and a manifest that lists these on it is refused by `validate`.

  hitl               a `stage` tool the manifest names in `gate` stops for a person before it runs. A staged card is
                     already a person's gate, so this is for a system that wants a second one; a `write` tool is never
                     on an agent at all (`validate`)
  retry              a failed model turn is retried (the tier's `retries`)
  fallback           the tier's `fallbacks` (models.yaml) are tried, in order, after the model fails; none = nothing
                     added
  limits             the loop is capped: the manifest's `max_tool_calls` calls and `max_model_calls` model rounds per
                     run (plan/2026-11-04 D2). Over the cap the agent is told to answer with what it has
  clear_old_results  the results of tool calls older than the last 3 are replaced by a short marker, so a long loop
                     does not pay for every lookup again on every round
  tool_retry         a `read` tool that raised is tried again (a flaky database read); `stage` tools never are
  tiering            the turn moves once, upward, to the manifest's `deep_model` when the work needs it (tiering.py,
                     plan/2026-11-08 §4.4). Built by the agent, which knows the run's start tier and its record
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from hiru_ai.core import llm
from hiru_ai.core.models import resolve

NAMES = ("hitl", "retry", "fallback", "limits", "clear_old_results", "tool_retry", "tiering")
KEEP_RESULTS = 3  # tool results kept whole by `clear_old_results`
CLEAR_AFTER_TOKENS = 3000  # editing starts once the thread is this long; short loops are left alone


def build(names: Sequence[str], *, tier: str, gated: Sequence[str] = (), read_tools: Sequence[str] = (),
          max_tool_calls: int = 6, max_model_calls: int = 4, tiering: Any = None) -> list[Any]:
    """The LangChain middleware the manifest asks for, outermost first. A request with nothing to do (`hitl` with no
    gated tool, `tool_retry` with no read tool, `fallback` on a tier with no fallbacks, `tiering` with no middleware
    built for it) adds nothing. `tiering` is the middleware `tiering.build` made for this run."""
    from langchain.agents.middleware import (
        ClearToolUsesEdit,
        ContextEditingMiddleware,
        HumanInTheLoopMiddleware,
        ModelCallLimitMiddleware,
        ModelFallbackMiddleware,
        ModelRetryMiddleware,
        ToolCallLimitMiddleware,
        ToolRetryMiddleware,
    )

    out: list[Any] = []
    spec = resolve(tier)
    for name in names:
        if name == "hitl" and gated:
            out.append(HumanInTheLoopMiddleware(interrupt_on=dict.fromkeys(gated, True)))
        elif name == "retry":
            out.append(ModelRetryMiddleware(max_retries=spec.retries))
        elif name == "fallback" and spec.fallbacks:
            first, *rest = (llm.get_llm(t) for t in spec.fallbacks)
            out.append(ModelFallbackMiddleware(first, *rest))
        elif name == "limits":
            out.append(ToolCallLimitMiddleware(run_limit=max_tool_calls, exit_behavior="continue"))
            out.append(ModelCallLimitMiddleware(run_limit=max_model_calls, exit_behavior="end"))
        elif name == "clear_old_results":
            out.append(ContextEditingMiddleware(edits=[
                ClearToolUsesEdit(trigger=CLEAR_AFTER_TOKENS, keep=KEEP_RESULTS)]))
        elif name == "tiering" and tiering is not None:
            out.append(tiering)
        elif name == "tool_retry" and read_tools:
            out.append(ToolRetryMiddleware(max_retries=2, tools=list(read_tools), on_failure="continue"))
    return out
