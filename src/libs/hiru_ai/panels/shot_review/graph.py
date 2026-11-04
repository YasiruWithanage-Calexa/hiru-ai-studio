"""shot_review: the `generate_critique` pattern configured by this folder's manifest. Ported from
`shot_producer/engine/critique.py` and the review round of `pipeline.design_scene`.

    graph = build(ctx, write=..., critique=..., accept=...)
    out = graph.invoke({"brief": {...}})        out["draft"] the design to use   out["notes"]   out["rounds"] 0 or 1

The loop is bounded by the manifest's `max_rounds` and ends the moment the critic has no notes. The writer is not
assumed to be reliable: a writer that raises propagates (the producer then falls back to its rules), a critic that
cannot answer is "content" (no notes, the first draft stands). If the critic's agent is switched off, there is no
review and the first draft stands.
"""
from __future__ import annotations

from typing import Any

from langgraph.graph.state import CompiledStateGraph

from hiru_ai.core.context import RunContext
from hiru_ai.core.manifest import PanelManifest
from hiru_ai.core.panels import PanelKit
from hiru_ai.core.patterns import generate_critique
from hiru_ai.core.registry import Registry
from hiru_ai.panels.shot_review.state import Accept, Critique, Write

ID = "shot_review"


def build(ctx: RunContext | None = None, registry: Registry | None = None, manifest: PanelManifest | None = None,
          *, write: Write, critique: Critique, accept: Accept) -> CompiledStateGraph[Any, Any, Any, Any]:
    kit = PanelKit(ID, ctx, registry, manifest)
    writer_id, critic_id = kit.role("writer")[1], kit.role("critic")[1]
    critic_on = kit.registry.components[("agent", critic_id)].manifest.status != "disabled"

    def ask_writer(inp: dict[str, Any]) -> Any:
        return kit.agent(writer_id).run(inp, kit.ctx)

    def ask_critic(inp: dict[str, Any]) -> Any:
        return kit.ask(critic_id, inp)

    return generate_critique(
        lambda state, notes: write(ask_writer, state["brief"], notes),
        lambda state, draft: critique(ask_critic, state["brief"], draft) if critic_on else [],
        lambda state, draft, revised: accept(state["brief"], draft, revised),
        max_rounds=kit.manifest.max_rounds)


def blank(registry: Registry | None = None,
          manifest: PanelManifest | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    return build(registry=registry, manifest=manifest, write=lambda ask, brief, notes: None,
                 critique=lambda ask, brief, draft: [],
                 accept=lambda brief, draft, revised: draft)
