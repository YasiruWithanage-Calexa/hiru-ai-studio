"""What a middleware wraps: one model call, described by a `ModelCall`.

Cross-cutting rules (usage rows, uploaded text is data, absent-safe, dialogue stays put, static prompt first) are
middleware that a manifest switches on by name. They are never copied into each agent. A middleware is a
callable `(call, ctx, next) -> result`; the manifest lists them outermost first.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from hiru_ai.core.context import RunContext
from hiru_ai.core.prompts import Prompt


class _Missing:
    def __repr__(self) -> str:
        return "<no fallback>"


MISSING: Any = _Missing()


@dataclass(frozen=True)
class Document:
    """Uploaded text. It is data: wrapped in tags and labelled, never instructions."""

    name: str
    role: str
    text: str


@dataclass
class ModelCall:
    component: str  # "agent:translator"
    phase: str  # the token_usage phase
    tier: str
    system: str
    user: str
    version: int = 1
    static: Prompt | None = None  # the static prefix `system` must start with (static_first)
    tools: str = ""  # a react agent's tool definitions as sent (Agent.tool_block): part of the cached prefix too
    documents: Sequence[Document] = ()  # appended to `user` inside tags (untrusted_text)
    images: Sequence[tuple[str, str]] = ()  # (mime, base64) pictures sent with the user message (the frame check)
    files: Sequence[tuple[str, str]] = ()  # (filename, base64) PDFs sent with the user message (the document reader)
    lines_before: Mapping[str, str] | None = None  # spoken lines as given, by line id (language_guard)
    lines_after: Callable[[Any], Mapping[str, str]] | None = None  # the lines a result carries, by line id
    fallback: Any = MISSING  # what absent_safe returns when the model is unavailable or fails
    config: dict[str, Any] = field(default_factory=dict)  # LangChain run config (callbacks, metadata)
    timeout_s: float | None = None  # replaces the tier's timeout (the agent manifest's `timeout_s`)
    memory_topics: tuple[str, ...] = ()  # the production memory topics the agent is given (manifest `memory`)
    memory_scope: Mapping[str, Any] | None = None  # what the call is about: place, people, episode (production_memory)


Next = Callable[[ModelCall], Any]


class Middleware(Protocol):
    name: str

    def __call__(self, call: ModelCall, ctx: RunContext, nxt: Next) -> Any: ...


def run_chain(middleware: Sequence[Middleware], call: ModelCall, ctx: RunContext, terminal: Next) -> Any:
    """Run `terminal(call)` inside the middleware, the first in the list outermost."""
    nxt = terminal
    for mw in reversed(middleware):
        nxt = (lambda inner, wrapper: lambda c: wrapper(c, ctx, inner))(nxt, mw)
    return nxt(call)
