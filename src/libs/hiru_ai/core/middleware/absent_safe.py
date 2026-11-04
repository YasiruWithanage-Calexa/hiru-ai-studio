"""`absent_safe`: no key or a failed call degrades to the call's fallback, and never errors (CLAUDE.md).

A call that sets no `fallback` is not covered: the error passes through, because a silent empty answer would be a
bug. A person's pause in a graph (`interrupt()`) is control flow, not a failure, and always passes through.
"""
from __future__ import annotations

from typing import Any

from langgraph.errors import GraphBubbleUp

from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ModelUnavailable
from hiru_ai.core.middleware.base import MISSING, ModelCall, Next
from hiru_ai.core.telemetry import logger

name = "absent_safe"
_log = logger("absent_safe")


class AbsentSafe:
    name = name

    def __call__(self, call: ModelCall, ctx: RunContext, nxt: Next) -> Any:
        try:
            return nxt(call)
        except GraphBubbleUp:
            raise
        except ModelUnavailable:
            if call.fallback is MISSING:
                raise
            _log.info("no model: using the fallback component=%s", call.component)
            return call.fallback
        except Exception:
            if call.fallback is MISSING:
                raise
            _log.warning("model call failed, using the fallback component=%s phase=%s", call.component, call.phase,
                         exc_info=True)
            return call.fallback
