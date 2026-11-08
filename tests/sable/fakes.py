"""Two fake models for Sable's tests: one per tier, each answering from its own queue and recording what it was sent
(the messages, the tools it was bound with, its tags). No network (CLAUDE.md "Tests never call OpenAI")."""
from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

from langchain_core.messages import AIMessage
from pydantic import Field

from hiru_ai.core import llm
from hiru_ai.core.context import RunContext
from hiru_ai.core.fakes import ports_from
from hiru_ai.core.testing import ScriptedChatModel

WORLD = Path(__file__).resolve().parents[2] / "src/libs/hiru_ai/tools/sable/sable_overview/examples/basic.json"


class TierModel(ScriptedChatModel):
    """A scripted model that remembers the tools it was bound with (the cached prefix must be the same bytes)."""

    bound: list[list[str]] = Field(default_factory=list)

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Any:
        self.bound.append([t.name if hasattr(t, "name") else str(t.get("name")) for t in tools])
        return self

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> Any:
        self.calls.append(list(messages))
        reply = self._next()
        if isinstance(reply, AIMessage):
            message = reply.model_copy(update={"usage_metadata": self._usage(),
                                               "response_metadata": {"model_name": self.model_name}})
        else:
            message = AIMessage(content=self._text(reply), usage_metadata=self._usage(),
                                response_metadata={"model_name": self.model_name})
        from langchain_core.outputs import ChatGeneration, ChatResult

        return ChatResult(generations=[ChatGeneration(message=message)])


def tool(name: str, n: int = 0, **args: Any) -> AIMessage:
    call: Any = {"name": name, "args": args, "id": f"call-{name}-{n}", "type": "tool_call"}
    return AIMessage(content="", tool_calls=[call])


def answer(text: str, handoff_scene: str = "", handoff_request: str = "") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": "Output", "args": {
        "text": text, "handoff_scene": handoff_scene, "handoff_request": handoff_request}, "id": "final",
        "type": "tool_call"}])


@contextmanager
def two_models(base: list[Any], deep: list[Any]) -> Iterator[tuple[TierModel, TierModel]]:
    """`sable` answers from `base`, `sable_deep` from `deep` (any other tier from `base`)."""
    b = TierModel(replies=list(base), model_name="base-model")
    d = TierModel(replies=list(deep), model_name="deep-model")
    with llm.use_models(lambda tier: d if tier.name == "sable_deep" else b):
        yield b, d


def world() -> dict[str, Any]:
    return dict(json.loads(WORLD.read_text(encoding="utf-8")))


def context(rows: list[Any] | None = None, *, scene: bool = True, **over: Any) -> RunContext:
    case = world()
    fields: dict[str, Any] = {
        "production_id": UUID(case["production_id"]), "scene_id": UUID(case["scene_id"]) if scene else None,
        "corpora": tuple(case.get("corpora") or ()), "ports": ports_from(case["fixtures"]),
        "usage_sink": rows.append if rows is not None else None}
    return RunContext(**{**fields, **over})
