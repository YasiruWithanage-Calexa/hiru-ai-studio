"""`house_rules`: the studio's own rules, appended to the agent's SYSTEM prompt (plan/2026-11-12 §3.1).

An agent subscribes with two lines in its manifest:

    middleware: [static_first, usage, house_rules]
    house_rules: [objects, sound]        # the topics it is given; `*` for every rule

The rules are files (`hiru_ai.core.house_rules`), the same for every call until the next deploy, so they go in the
system prompt after the part's own text: the prefix OpenAI caches is unchanged from call to call and `static_first`
still holds. No subscribed rule, no block: the call is byte for byte what it was before house rules existed. Which rules
a call was given (id and version) is recorded on the run and in the trace's metadata, so a plan can be traced to them.
"""

from __future__ import annotations

from typing import Any

from hiru_ai.core import house_rules
from hiru_ai.core.context import RunContext
from hiru_ai.core.middleware.base import ModelCall, Next

name = "house_rules"
_USED = "_house_rules_used"


def note_used(ctx: RunContext, chosen: list[house_rules.Rule]) -> None:
    """Record the rules a call was given, once each, in the order first given."""
    used: dict[str, str] = ctx.memory_cache.setdefault(_USED, {})
    for r in chosen:
        used.setdefault(r.id, r.label)


def used(ctx: RunContext) -> list[str]:
    """Every rule this run's agents were given so far, as "H-12 v2"."""
    return list(ctx.memory_cache.get(_USED, {}).values())


class HouseRules:
    name = name

    def __call__(self, call: ModelCall, ctx: RunContext, nxt: Next) -> Any:
        chosen = house_rules.select(call.house_topics)
        if not chosen:
            return nxt(call)
        call.system = house_rules.appended(call.system, call.house_topics)
        meta = dict(call.config.get("metadata") or {})
        meta["house_rules"] = [r.label for r in chosen]
        call.config = {**call.config, "metadata": meta}
        out = nxt(call)
        note_used(ctx, chosen)  # after the call: a call that failed relied on nothing
        return out
