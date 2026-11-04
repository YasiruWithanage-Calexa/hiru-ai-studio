"""director_board: the `board` pattern configured by this folder's manifest. Ported from
`director_chat/engine/agents.py` (`run_specialists`, `settle`, `advisor_review`).

    graph = build(ctx)
    out = graph.invoke({"brief": {"scene_text": ..., "lead_charter": ...}, "tasks": [...]})
    out["outputs"]   one Output per task, in task order     out["settled"].ops / .disagreements
    graph.invoke({"brief": ..., "reviews": [...]})["advice"]   the advisors, after the changes landed

A craft with no member (removed from the manifest, or its agent switched off) answers its tasks with no operations,
so the rest of the board is unaffected. A specialist may change only the shots its task names, and at most six
operations per task; the collision rule is the manifest's `wins:` table.
"""
from __future__ import annotations

from typing import Any

from langgraph.graph.state import CompiledStateGraph

from hiru_ai.core.context import RunContext
from hiru_ai.core.manifest import PanelManifest
from hiru_ai.core.panels import PanelKit
from hiru_ai.core.patterns import board
from hiru_ai.core.registry import Registry

ID = "director_board"
ADVICE_CHARS = 400
NOTE_CHARS = 300


def ownership(kit: PanelKit) -> dict[str, str]:
    """path → the member that wins a collision on it, from the members' `wins:`."""
    return {win: m.label for m in kit.members() for win in m.wins}


def allowed_ops(manifest: PanelManifest) -> dict[str, tuple[str, ...]]:
    """craft → the operations the kernel lets it write (what `ALLOWED` was)."""
    return {m.label: tuple(m.owns) for m in manifest.members}


def build(ctx: RunContext | None = None, registry: Registry | None = None,
          manifest: PanelManifest | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    kit = PanelKit(ID, ctx, registry, manifest)
    rules = kit.step(kit.manifest.settle)
    owners = ownership(kit)
    advisor_ids = kit.advisors()

    def specialist(task: dict[str, Any], state: dict[str, Any]) -> Any:
        craft = str(task.get("agent") or "")
        member = kit.member(craft)
        if member is None:
            return rules.Output(craft)
        brief = state.get("brief") or {}
        shots = [int(n) for n in task.get("shots") or []]
        answer = kit.ask(member.agent, {"lead_charter": brief.get("lead_charter", ""),
                                        "scene_text": brief.get("scene_text", ""), "shots": shots,
                                        "instruction": task.get("instruction", "")})
        if answer is None:
            return rules.Output(craft)
        ops = [{k: v for k, v in op.model_dump().items() if v is not None} for op in answer.ops]
        kept = [o for o in ops if rules.in_scope(o, shots)][:rules.MAX_OPS_PER_TASK]
        return rules.Output(craft, kept, str(answer.note)[:NOTE_CHARS])

    def advisor(item: dict[str, Any], state: dict[str, Any]) -> dict[str, str] | None:
        if not advisor_ids:
            return None
        answer = kit.ask(advisor_ids[0], {"charter": item.get("charter", ""), "summary": item.get("summary", ""),
                                          "scene_text": (state.get("brief") or {}).get("scene_text", "")})
        if answer is None or answer.agrees or not str(answer.view).strip():
            return None
        return {"who": str(item["name"]), "text": str(answer.view)[:ADVICE_CHARS]}

    return board(specialist, lambda outputs: rules.settle(outputs, owners), advisor if advisor_ids else None)


def blank(registry: Registry | None = None,
          manifest: PanelManifest | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    """The panel with nothing to run, for drawing and for compiling a changed manifest."""
    return build(registry=registry, manifest=manifest)
