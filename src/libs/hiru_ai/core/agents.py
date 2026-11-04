"""The two agent builders: `structured` (one typed call) and `react` (a `create_agent` tool loop).

An agent is a folder (prompt, `schema.py`, `agent.py` hooks, `component.yaml`, evals); this module turns the folder into
something that runs. The agent's own code is small and typed:

    schema.py   Input, Output           pydantic; the only things the agent shares with whoever calls it
    agent.py    user_message(inp)       per-item data for the USER message (the system prompt stays static)
                fallback(inp)           the rules-only answer, or None when there is none (optional)
                finish(inp, out)        the answer cleaned up exactly as the engine did (optional)
                documents(inp)          uploaded text, wrapped by the `untrusted_text` middleware (optional)
                images(inp)             (mime, base64) pictures sent with the user message (a vision agent; optional)
                output_schema()         a JSON schema (with a top-level `title`) when the shape is decided at run time
                lines_before(inp), lines_after(out)   spoken lines in and out, for `language_guard` (optional)

Everything cross-cutting is middleware the manifest names (usage rows, "document text is data", absent-safe, the
dialogue rule, a static prompt prefix), never copied into an agent. Dependencies arrive in the `RunContext`.

    agent = build("shot_critic")
    out = agent.run(Input(...), ctx)          # an Output; the fallback when the model is unavailable or fails
    system, user = agent.messages(Input(...)) # exactly what would be sent (tests, `hiru-ai run agent --dry`)
"""
from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from types import ModuleType
from typing import Any, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel

from hiru_ai.core import llm, middleware, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ManifestError
from hiru_ai.core.manifest import AgentManifest, ToolManifest
from hiru_ai.core.middleware import react
from hiru_ai.core.middleware.base import MISSING, Document, ModelCall
from hiru_ai.core.prompts import Prompt
from hiru_ai.core.registry import Registry
from hiru_ai.core.scope import scope_for
from hiru_ai.core.settings import agents_with_tools


class Agent:
    def __init__(self, registry: Registry, ident: str, *, with_tools: bool | None = None) -> None:
        """`with_tools`: run the manifest's `with_tools` form (a tool loop). None = as `AGENT_TOOLS` says; an agent
        with no such form always runs as its manifest says."""
        comp = registry.get("agent", ident)
        manifest = comp.manifest
        if not isinstance(manifest, AgentManifest):  # pragma: no cover - the registry keys by kind
            raise ManifestError(f"{ident} is not an agent")
        if with_tools is None:
            with_tools = ident in agents_with_tools()
        manifest = manifest.form(with_tools)
        self.registry, self.manifest, self.id = registry, manifest, ident
        self.input_cls: type[BaseModel] = registry.resolve("agent", ident, manifest.input)
        self.output_cls: type[BaseModel] = registry.resolve("agent", ident, manifest.output)
        self.hooks: ModuleType = registry.module("agent", ident, "agent")
        self.prompt = Prompt.load(comp.folder / manifest.prompts["system"])
        self.component = f"agent:{ident}"
        self._tools: list[Any] | None = None

    @property
    def phase(self) -> str:
        return self.manifest.phase or f"agent.{self.id}"

    @property
    def uses_tools(self) -> bool:
        """True when this agent runs as a tool loop: a caller then hands it a short summary and lets it look the rest up
        (plan/2026-11-04 §8), where it would otherwise pack the whole thing into the prompt."""
        return bool(self.manifest.tools)

    # ── what is sent ──────────────────────────────────────────────────────────────────────

    def _input(self, inp: BaseModel | dict[str, Any]) -> Any:
        return inp if isinstance(inp, self.input_cls) else self.input_cls.model_validate(inp)

    def messages(self, inp: BaseModel | dict[str, Any]) -> tuple[str, str]:
        """(system, user): the static prompt, and the per-item message the agent builds. Middleware may add to them."""
        tools_message = getattr(self.hooks, "tools_user_message", None) if self.uses_tools else None
        return self.prompt.system(), (tools_message or self.hooks.user_message)(self._input(inp))

    def prepare(self, inp: BaseModel | dict[str, Any]) -> ModelCall:
        inp = self._input(inp)
        system, user = self.messages(inp)
        hook = self.hooks
        fallback = getattr(hook, "fallback", None)
        answer = fallback(inp) if fallback else None
        before, after = getattr(hook, "lines_before", None), getattr(hook, "lines_after", None)
        docs = getattr(hook, "documents", None)
        images = getattr(hook, "images", None)
        return ModelCall(
            component=self.component, phase=self.phase, tier=self.manifest.model, system=system, user=user,
            version=self.manifest.version, static=self.prompt,
            tools=self.tool_block() if self.manifest.tools else "",
            documents=tuple(docs(inp)) if docs else (),
            images=tuple(images(inp)) if images else (),
            lines_before=before(inp) if before else None, lines_after=after,
            fallback=MISSING if answer is None else answer)

    # ── running ───────────────────────────────────────────────────────────────────────────

    def run(self, inp: BaseModel | dict[str, Any], ctx: RunContext | None = None, *,
            config: dict[str, Any] | None = None) -> Any:
        """The agent's Output. `ctx` carries the usage sink and the ports; without one the agent still runs."""
        inp, ctx = self._input(inp), ctx or RunContext()
        call = self.prepare(inp)
        call.config = dict(config or {})
        chain = middleware.build(self.manifest.middleware, writes_dialogue=self.manifest.writes_dialogue)
        terminal = {"structured": self._structured, "react": self._react, "text": self._text}[self.manifest.shape]
        return middleware.run_chain(chain, call, ctx, lambda c: self._finish(inp, terminal(c, ctx)))

    # ── a reply read as it is written (shape `text`) ──────────────────────────────────────────────────────────────

    def _chain(self, inp: BaseModel | dict[str, Any], ctx: RunContext, terminal: Callable[[ModelCall], Any]) -> Any:
        """Run `terminal` inside this agent's middleware, with its prompt and usage tags (text agents are not retried
        or fallen back by middleware: a half-streamed reply cannot be replaced, so the caller decides)."""
        call = self.prepare(self._input(inp))
        chain = middleware.build(self.manifest.middleware, writes_dialogue=self.manifest.writes_dialogue)
        return middleware.run_chain(chain, call, ctx, terminal)

    def stream(self, inp: BaseModel | dict[str, Any], ctx: RunContext | None = None, *,
               messages: list[BaseMessage] | None = None) -> Iterator[str]:
        """The reply as it is written, chunk by chunk. `messages` continues a conversation already started (tool
        results); the system prompt and the user message are this agent's own. A failure surfaces while iterating."""
        ctx = ctx or RunContext()

        def go(call: ModelCall) -> Iterator[str]:
            model = llm.get_llm(call.tier)
            thread = messages if messages is not None else [SystemMessage(call.system), HumanMessage(call.user)]
            for chunk in model.stream(thread, config=cast(Any, call.config)):
                text = chunk.content
                if isinstance(text, str) and text:
                    yield text

        out: Iterator[str] = self._chain(inp, ctx, go)
        return out

    def tool_rounds(self, inp: BaseModel | dict[str, Any], ctx: RunContext | None, *, tools: list[dict[str, Any]],
                    call_tool: Callable[[str, str], str], rounds: int = 3) -> tuple[str | None, list[BaseMessage]]:
        """Up to `rounds` calls that may ask for the read tools. -> (the answer, [] ) when a round asks for none, or
        (None, the conversation so far) when every round did: the caller then writes the reply from what was read."""
        ctx = ctx or RunContext()

        def go(call: ModelCall) -> tuple[str | None, list[BaseMessage]]:
            bound = llm.get_llm(call.tier).bind_tools(tools)
            thread: list[BaseMessage] = [SystemMessage(call.system), HumanMessage(call.user)]
            for _ in range(rounds):
                reply = bound.invoke(thread, config=cast(Any, call.config))
                asked = getattr(reply, "tool_calls", None) or []
                if not asked:
                    return str(reply.content or ""), thread
                thread.append(reply if isinstance(reply, AIMessage) else AIMessage(content=str(reply.content or "")))
                for tool in asked:
                    args = tool.get("args")
                    thread.append(ToolMessage(content=call_tool(tool["name"], args if isinstance(args, str)
                                                                else json.dumps(args or {})),
                                              tool_call_id=str(tool.get("id") or tool["name"])))
            return None, thread

        out: tuple[str | None, list[BaseMessage]] = self._chain(inp, ctx, go)
        return out

    def _finish(self, inp: Any, out: Any) -> Any:
        finish = getattr(self.hooks, "finish", None)
        return finish(inp, out) if finish else out

    def wire_schema(self) -> Any:
        """What the model is held to on the wire: the Output class, or the JSON schema the agent's `output_schema()`
        hook returns when the shape is decided at run time (the shot writer's clip schema is read from a YAML file)."""
        hook = getattr(self.hooks, "output_schema", None)
        return hook() if hook else self.output_cls

    def _structured(self, call: ModelCall, ctx: RunContext) -> Any:
        runnable = llm.get_structured(call.tier, self.wire_schema())
        user: Any = call.user
        if call.images:  # a vision call: the text, then each picture at low detail
            user = [{"type": "text", "text": call.user},
                    *({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}", "detail": "low"}}
                      for mime, data in call.images)]
        raw = runnable.invoke([SystemMessage(call.system), HumanMessage(content=user)], config=cast(Any, call.config))
        return raw if isinstance(raw, self.output_cls) else self.output_cls.model_validate(raw)

    def _text(self, call: ModelCall, ctx: RunContext) -> Any:
        """The whole reply as one `Output(text=...)` (a streamed reply is read with `stream`)."""
        reply = llm.get_llm(call.tier).invoke([SystemMessage(call.system), HumanMessage(call.user)],
                                              config=cast(Any, call.config))
        return self.output_cls.model_validate({"text": str(reply.content or "")})

    def tools(self) -> list[Any]:
        """The agent's tools, sorted by id and built once: the tool definitions are part of the cached prompt prefix, so
        they must be the same bytes on every call (plan/2026-11-04 §6.6)."""
        if self._tools is None:
            self._tools = [parts.module("tool", t, "tool").as_tool() for t in sorted(self.manifest.tools)]
        return self._tools

    def tool_block(self) -> str:
        """The tool definitions as sent (name, description, argument schema), for `static_first` and the tests."""
        return json.dumps([{"name": t.name, "description": t.description, "args": t.args} for t in self.tools()],
                          sort_keys=True, ensure_ascii=False)

    def _tool_ids(self, effect: str) -> list[str]:
        out = []
        for t in sorted(self.manifest.tools):
            tool = self.registry.get("tool", t).manifest
            if isinstance(tool, ToolManifest) and tool.effect == effect:
                out.append(t)
        return out

    def _react(self, call: ModelCall, ctx: RunContext) -> Any:
        from langchain.agents import create_agent

        m = self.manifest
        run_ctx = scope_for(ctx, m.knowledge, self.registry) if m.knowledge else ctx  # it may search only its bases
        agent = create_agent(
            llm.get_llm(call.tier), self.tools(), system_prompt=call.system, response_format=self.output_cls,
            middleware=react.build(m.middleware, tier=m.model, gated=sorted(m.gate), read_tools=self._tool_ids("read"),
                                   max_tool_calls=m.max_tool_calls, max_model_calls=m.max_model_calls),
            context_schema=RunContext, name=self.id)
        result: Any = agent.invoke(cast(Any, {"messages": [HumanMessage(call.user)]}), config=cast(Any, call.config),
                                   context=run_ctx)
        return result["structured_response"]


def build(ident: str, registry: Registry | None = None, *, with_tools: bool | None = None) -> Agent:
    """The agent with this id. A disabled or missing agent raises `UnknownComponent`."""
    return Agent(registry or parts._registry(), ident, with_tools=with_tools)


__all__ = ["Agent", "Document", "build"]
