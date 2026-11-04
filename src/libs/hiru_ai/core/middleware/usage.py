"""`usage`: a `token_usage` row for every model call, and trace tags saying which part made it."""
from __future__ import annotations

from typing import Any

from hiru_ai.core.context import RunContext
from hiru_ai.core.middleware.base import ModelCall, Next
from hiru_ai.core.prompts import sha
from hiru_ai.core.telemetry import Tags
from hiru_ai.core.usage import Detail, UsageCallback

name = "usage"


class Usage:
    name = name

    def __call__(self, call: ModelCall, ctx: RunContext, nxt: Next) -> Any:
        prompt_hash = call.static.sha if call.static else sha(call.system)
        detail = Detail(call.component, call.version, prompt_hash) if ctx.usage_detail else None
        callback = UsageCallback(ctx.sink(), call.phase, detail=detail)
        tags = Tags(call.component, call.version, prompt_hash, call.phase)
        config = {**call.config,
                  "callbacks": [*call.config.get("callbacks", []), callback],
                  "metadata": {**call.config.get("metadata", {}), **tags.metadata()}}
        call.config = config
        return nxt(call)
