"""Test fakes: models that answer from a script and never touch the network (CLAUDE.md "Tests never call OpenAI").

    model = ScriptedChatModel(replies=[Shot(title="T", seconds=6)])
    with use_models(model):
        get_structured("high", Shot).invoke(messages)

`ScriptedChatModel` is a real LangChain chat model: it supports `with_structured_output`, reports
`usage_metadata` (so the usage callback sees tokens) and records every call it receives.
"""
from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel, Field


class ScriptedChatModel(BaseChatModel):
    """Answers from `replies`, in order. A reply is text, a dict, or a pydantic model; an exception is raised.

    Out of replies: raises `RuntimeError`, like an unreachable model (so absent-safe paths can be tested).
    """

    replies: list[Any] = Field(default_factory=list)
    calls: list[list[BaseMessage]] = Field(default_factory=list)
    model_name: str = "scripted"
    input_tokens: int = 100
    cached_tokens: int = 0
    output_tokens: int = 20

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _next(self) -> Any:
        if not self.replies:
            raise RuntimeError("no scripted reply left")
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    @staticmethod
    def _text(reply: Any) -> str:
        if isinstance(reply, BaseModel):
            return reply.model_dump_json()
        return reply if isinstance(reply, str) else json.dumps(reply)

    def _usage(self) -> dict[str, Any]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "total_tokens": self.input_tokens + self.output_tokens,
                "input_token_details": {"cache_read": self.cached_tokens}}

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                  run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any) -> ChatResult:
        self.calls.append(list(messages))
        message = AIMessage(content=self._text(self._next()), usage_metadata=self._usage(),
                            response_metadata={"model_name": self.model_name})
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(self, messages: list[BaseMessage], stop: list[str] | None = None,
                run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any) -> Iterator[ChatGenerationChunk]:
        self.calls.append(list(messages))
        text = self._text(self._next())
        half = max(1, len(text) // 2)
        yield ChatGenerationChunk(message=AIMessageChunk(content=text[:half]))
        yield ChatGenerationChunk(message=AIMessageChunk(
            content=text[half:], usage_metadata=self._usage(),  # type: ignore[arg-type]
            response_metadata={"model_name": self.model_name}))

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable[Any, Any]:
        def parse(message: BaseMessage) -> Any:
            data = json.loads(message.content if isinstance(message.content, str) else "")
            return schema.model_validate(data) if isinstance(schema, type) and issubclass(schema, BaseModel) else data

        return self | RunnableLambda(parse)

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable[Any, Any]:
        return self


_ROUTE_LOCK = threading.Lock()  # one lock for every RoutedChatModel: instances that share queues must not race


class RoutedChatModel(ScriptedChatModel):
    """Answers from one queue per ROUTE, the route chosen by `choose(messages)`.

    Parallel branches (a board's specialists, a panel's critics) reach the model in no fixed order, so a single queue
    of replies would hand the wrong answer to the wrong member. The route is whatever tells them apart, usually a
    phrase of the system prompt:

        RoutedChatModel(routes={"sound": [reply]}, choose=lambda m: "sound" if "sound" in m[0].content else "editor")

    A route with no reply left raises, like an unreachable model; a route nobody asked for is left alone.
    """

    # Typed Any so that several instances (one per tier) can SHARE one set of queues and one record of calls.
    routes: Any = Field(default_factory=dict)  # route -> list of replies
    choose: Any = None  # Callable[[list[BaseMessage]], str]; None = route by the call's `phase` (usage middleware)
    phases: Any = Field(default_factory=list)  # the phase of every call, in the order the calls arrived
    models: Any = Field(default_factory=list)  # the model id each call used (one instance per tier)
    calls: Any = Field(default_factory=list)
    chunk_at: int | None = None  # where a streamed reply is cut in two (None = the middle)
    stream_phase: str = ""  # the phase (route) of every streamed call: a streamed call carries no metadata

    def _next(self) -> Any:  # pragma: no cover - replaced by _generate below
        raise RuntimeError("RoutedChatModel picks its reply per call")

    def _route(self, messages: list[BaseMessage], metadata: dict[str, Any]) -> Any:
        chooser: Callable[[list[BaseMessage]], str] | None = self.choose
        with _ROUTE_LOCK:
            self.calls.append(list(messages))
            self.phases.append(str(metadata.get("phase", "")))
            self.models.append(self.model_name)
            queue = self.routes.get(chooser(messages) if chooser else str(metadata.get("phase", ""))) or []
            if not queue:
                raise RuntimeError("no scripted reply left for this route")
            reply = queue.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply(messages) if callable(reply) else reply  # a reply may be built from the prompt it answers

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                  run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any) -> ChatResult:
        metadata = dict(getattr(run_manager, "metadata", None) or {})
        reply = self._route(messages, metadata)
        if isinstance(reply, AIMessage):  # a whole message, with its tool calls
            message = reply.model_copy(update={"usage_metadata": self._usage(),
                                               "response_metadata": {"model_name": self.model_name}})
        else:
            message = AIMessage(content=self._text(reply), usage_metadata=self._usage(),
                                response_metadata={"model_name": self.model_name})
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(self, messages: list[BaseMessage], stop: list[str] | None = None,
                run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any) -> Iterator[ChatGenerationChunk]:
        # LangChain gives a streamed call no run manager, so no metadata: the phase of a streamed reply is given
        text = self._text(self._route(messages, {"phase": self.stream_phase}))
        cut = self.chunk_at if self.chunk_at is not None else max(1, len(text) // 2)
        yield ChatGenerationChunk(message=AIMessageChunk(content=text[:cut]))
        yield ChatGenerationChunk(message=AIMessageChunk(
            content=text[cut:], usage_metadata=self._usage(),  # type: ignore[arg-type]
            response_metadata={"model_name": self.model_name}))


def no_real_models(monkeypatch: Any) -> None:
    """Tests never call OpenAI (CLAUDE.md): an empty key beats the one in a developer's `.env`, and the settings
    cache is cleared so the empty key is what `get_settings()` reads. Used by the autouse fixture of every hiru_ai
    test folder."""
    from hiru_ai.core.settings import get_settings

    monkeypatch.setenv("OPENAI__API_KEY", "")
    monkeypatch.setenv("AGENT_TOOLS", "")  # a developer's switch never changes what a test builds
    monkeypatch.setenv("BREAKDOWN__ENABLED", "false")  # nor the scene breakdown's (plan/2026-11-11)
    monkeypatch.setenv("RAPHAEL_PACKET", "false")
    get_settings.cache_clear()


# ── tools: run one on its own example ────────────────────────────────────────────────────────────────────────────────


def example_of(tool_id: str) -> dict[str, Any]:
    """A tool's `examples/basic.json`: the fixtures its ports hold and the arguments of one call."""
    import json

    from hiru_ai.core.registry import default

    return json.loads((default().get("tool", tool_id).folder / "examples" / "basic.json").read_text(encoding="utf-8"))


def example_ctx(case: dict[str, Any], **over: Any) -> Any:
    """The `RunContext` an example describes (production, scene in scope, the person's words, corpora, in-memory ports).
    `over` replaces any field: `example_ctx(case, scene_id=None)`."""
    from uuid import UUID

    from hiru_ai.core.context import RunContext
    from hiru_ai.core.fakes import ports_from

    fields: dict[str, Any] = {
        "production_id": UUID(case["production_id"]) if case.get("production_id") else None,
        "scene_id": UUID(case["scene_id"]) if case.get("scene_id") else None,
        "said": str(case.get("said") or ""), "corpora": tuple(case.get("corpora") or ()),
        "ports": ports_from(case.get("fixtures") or {})}
    return RunContext(**{**fields, **over})


def run_example(tool_id: str, args: dict[str, Any] | None = None, **over: Any) -> tuple[Any, Any]:
    """Run a tool on its example (with `args` laid over the example's own) → (its Result, the RunContext used)."""
    from hiru_ai.core.registry import default

    case = example_of(tool_id)
    ctx = example_ctx(case, **over)
    module = default().module("tool", tool_id, "tool")
    return module.run(module.Args.model_validate({**case["args"], **(args or {})}), ctx), ctx
