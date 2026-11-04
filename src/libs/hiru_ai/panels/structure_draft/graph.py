"""structure_draft: the `fanout` pattern over the drafting agents of the structure build. Ported from the thread pools
of `structure_build/engine/prose.py` (`convert`), `architect.py` (`name_all`) and `looks.py`.

    graph = build(ctx)
    graph.invoke({"items": [Job, ...]})["outputs"]       one Result per job, in job order

A model's answer is never trusted on its own: `ok=False` (no member, or the agent could not answer) sends the caller
to its rules, and the caller checks an `ok` answer in code (the prose cut must keep every spoken line word for word).
"""
from __future__ import annotations

from typing import Any

from langgraph.graph.state import CompiledStateGraph

from hiru_ai.core.context import RunContext
from hiru_ai.core.manifest import PanelManifest
from hiru_ai.core.panels import PanelKit
from hiru_ai.core.patterns import fanout
from hiru_ai.core.registry import Registry

ID = "structure_draft"


def build(ctx: RunContext | None = None, registry: Registry | None = None,
          manifest: PanelManifest | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    kit = PanelKit(ID, ctx, registry, manifest)

    def work(job: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        name, key = str(job.get("member") or ""), str(job.get("key") or "")
        member = kit.member(name)
        if member is None:
            return {"member": name, "key": key, "ok": False, "output": None}
        answer = kit.ask(member.agent, job.get("input") or {})
        return {"member": name, "key": key, "ok": answer is not None, "output": answer}

    return fanout(work, name="draft")


def blank(registry: Registry | None = None,
          manifest: PanelManifest | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    return build(registry=registry, manifest=manifest)
