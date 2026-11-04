"""Running a migrated system against the parity fixtures (the `graph` engine, plan/2026-11-03 Phase 6).

The legacy adapters build fakes of the OpenAI SDK and of each service's store. The graph engine takes the same
fixtures: the store fakes already satisfy the ports (they were written from the same methods), and the scripted model
replies are routed to the new model door by `phase`, so a fixture needs no change.
"""
from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel

from hiru_ai.core import llm
from hiru_ai.core.models import Tier
from hiru_ai.core.settings import get_settings
from hiru_ai.core.testing import RoutedChatModel
from tests.parity.harness import sha

USAGE_COLUMNS = ("phase", "model", "input_tokens", "cached_input_tokens", "output_tokens")


class Endless(list):  # type: ignore[type-arg]
    """A queue whose reply is never used up (a fake that answers every call the same way)."""

    def pop(self, index: int = -1) -> Any:
        return self[0]


@dataclass
class Recorded:
    """What the routed model saw, in the order the calls arrived."""

    routes: dict[str, list[Any]]
    calls: list[Any] = field(default_factory=list)
    phases: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    tier_of: dict[str, str] = field(default_factory=dict)  # model id -> tier name

    def llm_calls(self, schema_of: dict[str, str]) -> list[dict[str, Any]]:
        """The calls as the parity outcome records them: schema, tier, phase and a hash of the system prompt."""
        return [{"schema": schema_of.get(phase, phase), "tier": self.tier_of.get(model, model), "phase": phase,
                 "system": sha(str(call[0].content))}
                for call, phase, model in zip(self.calls, self.phases, self.models, strict=True)]


@contextmanager
def environment(**env: str) -> Iterator[None]:
    """Set the environment the settings read, clear their cache, and put everything back."""
    before = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    get_settings.cache_clear()
    try:
        yield
    finally:
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


@contextmanager
def scripted_models(routes: dict[str, list[Any]], tiers: dict[str, str] | None = None, *,
                    chunk_at: int | None = None, stream_phase: str = "") -> Iterator[Recorded]:
    """The chat model door answers from `routes` (phase -> queue of replies). One model instance per tier, sharing
    queues, so a call knows which tier made it."""
    recorded = Recorded(routes, tier_of={model: tier for tier, model in (tiers or {}).items()})

    def factory(tier: Tier) -> BaseChatModel:
        return RoutedChatModel(routes=recorded.routes, calls=recorded.calls, phases=recorded.phases,
                               models=recorded.models, model_name=tier.model, chunk_at=chunk_at,
                               stream_phase=stream_phase)

    with llm.use_models(factory):
        yield recorded


def usage_row_filter(rows: list[dict[str, Any]]) -> Callable[[dict[str, Any]], None]:
    """A usage sink that keeps only the table's own columns, as the legacy fakes recorded them."""
    return lambda row: rows.append({k: row[k] for k in USAGE_COLUMNS})
