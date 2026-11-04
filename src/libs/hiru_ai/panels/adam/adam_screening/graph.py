"""adam_screening: the `critics_judge` pattern configured by this folder's manifest (plan/2026-11-04b §5.4).

The same pattern as `plan_review`, which screens the classic planner's shot lists, built on Adam's own parts.

    graph = build(ctx)
    out = graph.invoke({"brief": {"scene": SceneScript}, "candidates": [first_plan], "lenses": lenses(kit)})
    out["candidates"][out["winner"]]   the plan to use      out["notes"]    what the critics said (merged)
    out["results"]                     each critic's {lens, score, notes}, None for one that failed: the scores are for
                                       a person to read, they decide nothing

A candidate is an `AdamPlan` as data (aliases kept). The four critics run in parallel, each with its own lens; a
critic that fails is left out; with notes, ONE revision is made by the reviser, as operations on the plan, and
`adam_fidelity` drops
any added moment that invents story before the revision is scored. `adam_score` (code) picks, a fidelity break or an
overrun losing first; a revision replaces the first plan only when it is strictly better.

`evaluate(kit, scene, plan)` is the code's whole opinion of one plan (the reports and the score), for the caller's own
records.
"""
from __future__ import annotations

import threading
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from contracts.adam.plan import AdamPlan
from contracts.adam.screening import drop_moments, remap_sound
from hiru_ai.core.context import RunContext
from hiru_ai.core.manifest import PanelManifest
from hiru_ai.core.panels import PanelKit
from hiru_ai.core.patterns import critics_judge
from hiru_ai.core.registry import Registry

ID = "adam_screening"
REPORTS = ("fidelity", "fit", "continuity", "feasibility")


def lenses(kit: PanelKit) -> list[str]:
    return kit.names()


def dump(plan: AdamPlan) -> dict[str, Any]:
    return dict(plan.model_dump(mode="json", by_alias=True))


def evaluate(kit: PanelKit, scene: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """The code's reports on one plan and its craft score: `{"fidelity", "fit", "continuity", "feasibility", "score",
    "rank"}`. A plan that cannot be read is a loss, never an exception."""
    base = {"scene": scene, "plan": plan}
    editorial = bool((plan.get("report") or {}).get("editorial"))  # the production trims takes: runtimes count use_s
    found = {}
    for name in REPORTS:
        asked = {**base, "editorial": editorial} if name == "fit" else base
        found[name] = kit.step(f"step:adam_{name}", "step").run(asked)
    score = kit.step(kit.manifest.judge, "step").run({**base, **found})
    return {**found, "score": score, "rank": kit.step(kit.manifest.judge).rank(score)}


def build(ctx: RunContext | None = None, registry: Registry | None = None,
          manifest: PanelManifest | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    kit = PanelKit(ID, ctx, registry, manifest)
    notes = kit.step("step:adam_notes", "step")
    fidelity = kit.step("step:adam_fidelity", "step")
    reviser_id = kit.role("reviser")[1] if kit.has("reviser") else ""
    cache: dict[int, dict[str, Any]] = {}  # the first plan's evaluation, made once for every critic that wants it
    lock = threading.Lock()

    def first_eval(state: dict[str, Any]) -> dict[str, Any]:
        with lock:
            if 0 not in cache:
                cache[0] = evaluate(kit, state["brief"]["scene"], state["candidates"][0])
            return cache[0]

    def screen_input(state: dict[str, Any], **extra: Any) -> dict[str, Any]:
        plan = state["candidates"][0]
        keep = ("analysis", "treatment", "moments", "staging", "cards", "sound_map")
        return {"scene": state["brief"]["scene"], **{k: plan[k] for k in keep}, **extra}

    def critic(lens: str, state: dict[str, Any]) -> dict[str, Any] | None:
        member = kit.member(lens)
        if member is None:
            return None
        report = ""
        if lens == "fidelity":  # the one critic that reads what the code found
            found = first_eval(state)
            report = notes.run({**{k: found[k] for k in REPORTS}, "score": found["score"]})["text"]
        answer = kit.ask(member.agent, screen_input(state, report=report))
        if answer is None:
            return None
        return {"lens": lens, "score": answer.score, "notes": [n.model_dump() for n in answer.notes]}

    def merged(results: list[Any]) -> list[str]:
        if results and all(r is None for r in results):
            raise RuntimeError("every critic failed")
        return list(notes.run({"results": results})["notes"])

    def revise(state: dict[str, Any], lines: list[str]) -> dict[str, Any]:
        first = AdamPlan.model_validate(state["candidates"][0])
        found = first_eval(state)
        report = notes.run({**{k: found[k] for k in REPORTS}, "score": found["score"]})["text"]
        answer = kit.agent(reviser_id).run(screen_input(state, report=report, notes=lines), kit.ctx)
        revised = answer.apply(first.moments, first.cards)
        moments, cards = revised.moments, revised.cards
        numbers = dict(revised.renumbered)
        # An added moment that invents story is dropped here, so the revision is scored on what it may keep.
        scene = state["brief"]["scene"]
        check = fidelity.run({"scene": scene, "moments": [m.model_dump(mode="json") for m in moments]})
        if check["dropped"]:
            moments, cards, again = drop_moments(moments, cards, set(check["dropped"]))
            numbers = {old: again[new] for old, new in numbers.items() if new in again}
        sound = remap_sound(first.sound_map, numbers, {m.id for m in moments})
        report_note = {**first.report, "revision": {"operations": len(answer.operations), "skipped": revised.skipped,
                                                    "dropped": check["dropped"]}}
        return dump(first.model_copy(update={"moments": moments, "cards": cards, "sound_map": sound,
                                             "report": report_note}))

    def score(candidate: Any, state: dict[str, Any]) -> Any:
        return evaluate(kit, state["brief"]["scene"], candidate)["rank"]

    return critics_judge(critic, merged, revise if reviser_id else None, score)


def blank(registry: Registry | None = None,
          manifest: PanelManifest | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    return build(registry=registry, manifest=manifest)
