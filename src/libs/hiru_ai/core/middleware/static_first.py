"""`static_first`: the prompt's static part comes first and is byte-identical on every call (cache hits).

OpenAI reuses work for a prompt's leading bytes, and the tool definitions are part of those bytes. So the system message
must START with the part's static prompt, unchanged, per-item data must not leak into it, and a react agent's tool block
must be the same on every call (sorted by name, the same descriptions). With `ctx.strict` (tests) a violation raises;
otherwise it is logged, because a lost cache hit costs money but is not a reason to fail a person's job.
"""
from __future__ import annotations

import json
from typing import Any

from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import StaticPrefixError
from hiru_ai.core.middleware.base import ModelCall, Next
from hiru_ai.core.prompts import sha
from hiru_ai.core.telemetry import logger

name = "static_first"
_log = logger("static_first")
# (component, version, tools) → the hash of the tool block first sent
_tool_blocks: dict[tuple[str, int, tuple[str, ...]], str] = {}


def _drift(call: ModelCall) -> str:
    """What is wrong with the call's tool block, if anything: not sorted, or different from the one sent before."""
    if not call.tools:
        return ""
    try:
        names = [t["name"] for t in json.loads(call.tools)]
    except (ValueError, KeyError, TypeError):
        return f"{call.component}: the tool block is not the agent's tool definitions"
    if names != sorted(names):
        return f"{call.component}: the tools are not sorted by id ({', '.join(names)}); the cached prefix would drift"
    seen = _tool_blocks.setdefault((call.component, call.version, tuple(names)), sha(call.tools))
    if seen != sha(call.tools):
        return f"{call.component}: the tool definitions changed between calls (a description or an argument)"
    return ""


class StaticFirst:
    name = name

    def __call__(self, call: ModelCall, ctx: RunContext, nxt: Next) -> Any:
        if call.static is not None and not call.system.startswith(call.static.text):
            message = f"{call.component}: the system prompt does not start with the part's static prompt"
            if ctx.strict:
                raise StaticPrefixError(message)
            _log.warning(message)
        if call.user and call.user in call.system:  # per-item data placed in the cached prefix
            message = f"{call.component}: per-item text was put in the system prompt"
            if ctx.strict:
                raise StaticPrefixError(message)
            _log.warning(message)
        if message := _drift(call):
            if ctx.strict:
                raise StaticPrefixError(message)
            _log.warning(message)
        return nxt(call)
