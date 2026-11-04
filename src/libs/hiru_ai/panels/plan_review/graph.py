"""plan_review: the `critics_judge` pattern configured by this folder's manifest. Ported from
`script_split/engine/critic.py`
(`review`) and the re-plan round of `pipeline.plan_scene`.

    graph = build(ctx)
    out = graph.invoke({"brief": Brief, "candidates": [first_plan], "lenses": graph_lenses})
    out["candidates"][out["winner"]]   the plan to use      out["notes"]   what the critics said

`lenses` is `lenses(manifest)`: the critics that are switched on. The critics run in parallel; a critic that fails is
left out; with notes, ONE revised plan is made by the planner; the kernel score (a step: code) picks, and a revision
replaces the first plan only when it is strictly better. The caller compares the winner with the rules' plan, as the
splitter always did, because the rules' plan is not made by this panel.
"""
from __future__ import annotations

from typing import Any

from langgraph.graph.state import CompiledStateGraph

from contracts.shotplan import ProposedShot, fit
from hiru_ai.core.context import RunContext
from hiru_ai.core.manifest import PanelManifest
from hiru_ai.core.panels import PanelKit
from hiru_ai.core.patterns import critics_judge
from hiru_ai.core.registry import Registry

ID = "plan_review"
TITLE_CHARS = 80


def lenses(kit: PanelKit) -> list[str]:
    return kit.names()


def build(ctx: RunContext | None = None, registry: Registry | None = None,
          manifest: PanelManifest | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    kit = PanelKit(ID, ctx, registry, manifest)
    judge = kit.step(kit.manifest.judge)
    merge = kit.step("step:note_merge")
    planner_id = kit.role("reviser")[1] if kit.has("reviser") else ""

    def critic(lens: str, state: dict[str, Any]) -> list[tuple[int, str]] | None:
        member = kit.member(lens)
        if member is None:
            return None
        brief = state["brief"]
        first = state["candidates"][0]
        answer = kit.ask(member.agent, {"listing": brief["listing"],
                                        "shot_list": judge.describe(first, brief["items"]),
                                        "reading": brief.get("reading_text", ""),
                                        "staging": brief.get("staging_text", ""), "found": brief.get("found", [])})
        return None if answer is None else merge.notes_of(answer.model_dump(mode="json"))

    def merged(results: list[Any]) -> list[str]:
        if results and all(r is None for r in results):
            raise RuntimeError("every reviewer failed")
        return list(merge.merge_notes([r or [] for r in results]))

    def revise(state: dict[str, Any], notes: list[str]) -> Any:
        brief = state["brief"]
        answer = kit.agent(planner_id).run({**brief["plan_input"], "notes": notes}, kit.ctx)
        if not answer.shots:
            raise ValueError("the planner returned no shots")
        proposal = [ProposedShot(s.start, s.end, s.framing, s.title[:TITLE_CHARS], s.sound_mode, s.duration, False,
                                 s.camera_link) for s in answer.shots]
        return fit(brief["items"], proposal, envelope_s=brief["envelope_s"], fixed_seconds=brief.get("fixed_seconds"))

    def score(candidate: Any, state: dict[str, Any]) -> Any:
        brief = state["brief"]
        return judge.kernel_score(candidate, brief.get("reading"), brief["items"], brief.get("staging"),
                                  list(brief.get("cast") or []))

    return critics_judge(critic, merged, revise if planner_id else None, score)


def blank(registry: Registry | None = None,
          manifest: PanelManifest | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    return build(registry=registry, manifest=manifest)
