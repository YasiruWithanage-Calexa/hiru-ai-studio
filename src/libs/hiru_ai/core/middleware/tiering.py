"""`tiering`: a `react` agent starts a turn on its manifest's tier and moves ONCE, only upward, to its deep tier when
the work needs it (plan/2026-11-08 §4.4). Generic: any `react` agent that names a `deep_model` may use it; Sable is the
first.

A turn picks its model in three steps, at most one switch:

  route      the caller started the run on the deep tier already (`Agent.run(..., tier=deep)`: a code pre-route such as
             `steps/sable/sable_route`). Nothing switches; the record says `route`
  model      the model called the manifest's `escalate_tool` (Sable's `sable_think_harder`): every LATER model call of
             the turn runs on the deep tier, with every tool result already read (it continues the thread; it does not
             start again)
  refusals   two tool calls in a row answered a refusal (`{"error", "how_to_fix"}`)
  cap        the turn used its `max_tool_calls`: the final answer is written on the deep tier
  stage      the base model asked for a `stage` tool (a card a person will act on): that round is drafted again on the
             deep tier, so the card is the deep model's

`escalate_on` (manifest) says which of model / refusals / cap / stage are on; the lab decides which stay. The tool list
and the system prompt are the same bytes on both tiers (only the model changes), so each tier's prompt cache stays warm.

The record (`RunContext.tiering`) is `{tier_start, tier_end, escalated_by, reason}`; the `token_usage` phase of a deep
call is `<phase prefix>.deep` (`sable.turn` → `sable.deep`) and a deep call carries the trace tag `<agent>:deep`.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from typing import Any

SIGNALS = ("model", "refusals", "cap", "stage")
REFUSALS_IN_A_ROW = 2


def deep_phase(phase: str) -> str:
    """`sable.turn` → `sable.deep`; a phase with no dot gets `.deep` added."""
    return f"{phase.rsplit('.', 1)[0]}.deep" if "." in phase else f"{phase}.deep"


def refused(content: Any) -> bool:
    """A tool answer that is a refusal or a failed lookup (`tooling.from_part` answers `{"error", "how_to_fix"}`)."""
    if not isinstance(content, str) or not content.startswith("{"):
        return False
    try:
        data = json.loads(content)
    except ValueError:
        return False
    return isinstance(data, dict) and bool(data.get("error"))


def build(*, agent: str, start: str, deep: str, escalate_tool: str = "", stage_tools: Sequence[str] = (),
          signals: Sequence[str] = SIGNALS, max_tool_calls: int = 6, record: dict[str, Any] | None = None,
          on_escalate: Callable[[str], None] | None = None, get_model: Callable[[str], Any] | None = None) -> Any:
    """The LangChain middleware. `record` is filled as the turn goes (the caller keeps it); `on_escalate(by)` is told
    once, when the switch happens (the usage callback's phase, a status line); `get_model(tier)` builds a model
    (`core.llm.get_llm` by default)."""
    from langchain.agents.middleware import AgentMiddleware
    from langchain_core.messages import AIMessage, ToolMessage

    from hiru_ai.core import llm

    make = get_model or llm.get_llm
    wanted = frozenset(signals)
    stages = frozenset(stage_tools)

    class Tiering(AgentMiddleware):
        name = "tiering"

        def __init__(self) -> None:
            super().__init__()
            self.record: dict[str, Any] = record if record is not None else {}
            self.record.update({"tier_start": start, "tier_end": start, "escalated_by": "", "reason": ""})
            self.escalated = start == deep
            if self.escalated:
                self.record["escalated_by"] = "route"
            self.tool_calls = 0
            self.refusals = 0
            self._deep: Any = None

        # ── the switch ────────────────────────────────────────────────────────────────────────────────────────

        def escalate(self, by: str, reason: str = "") -> None:
            if self.escalated:
                return  # once per turn, and never back down
            self.escalated = True
            self.record.update({"tier_end": deep, "escalated_by": by, "reason": reason[:200]})
            if on_escalate is not None:
                on_escalate(by)

        def deep_model(self) -> Any:
            if self._deep is None:
                model = make(deep)
                tags = [*(getattr(model, "tags", None) or []), f"{agent}:deep"]
                try:
                    model = model.model_copy(update={"tags": tags})
                except Exception:  # pragma: no cover - a model that cannot be copied keeps its own tags
                    logging.getLogger(__name__).debug("the deep model keeps its own tags", exc_info=True)
                self._deep = model
            return self._deep

        # ── model calls ───────────────────────────────────────────────────────────────────────────────────────

        def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
            if self.escalated:
                return handler(request.override(model=self.deep_model()))
            response = handler(request)
            if "stage" in wanted and stages and self._asks_stage(response):
                self.escalate("stage", "a card a person will act on")
                return handler(request.override(model=self.deep_model()))
            return response

        @staticmethod
        def _asks_stage(response: Any) -> bool:
            messages = getattr(response, "result", None)
            if messages is None:
                messages = [response]
            for message in messages:
                if isinstance(message, AIMessage) and any(c.get("name") in stages for c in message.tool_calls or []):
                    return True
            return False

        # ── tool calls ────────────────────────────────────────────────────────────────────────────────────────

        def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
            call = request.tool_call
            name = str(call.get("name") or "")
            result = handler(request)
            self.tool_calls += 1
            if escalate_tool and name == escalate_tool and "model" in wanted:
                args = call.get("args") or {}
                self.escalate("model", str(args.get("reason") or "") if isinstance(args, dict) else "")
            content = result.content if isinstance(result, ToolMessage) else None
            self.refusals = self.refusals + 1 if refused(content) else 0
            if "refusals" in wanted and self.refusals >= REFUSALS_IN_A_ROW:
                self.escalate("refusals", f"{self.refusals} lookups in a row were refused")
            if "cap" in wanted and self.tool_calls >= max_tool_calls:
                self.escalate("cap", f"used all {max_tool_calls} lookups")
            return result

    return Tiering()


__all__ = ["REFUSALS_IN_A_ROW", "SIGNALS", "build", "deep_phase", "refused"]
