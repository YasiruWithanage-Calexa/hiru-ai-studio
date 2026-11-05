"""adam_screening: the `critics_judge` pattern configured by this folder's manifest (plan/2026-11-04b §5.4).

The same pattern as `plan_review`, which screens the classic planner's shot lists, built on Adam's own parts.

    graph = build(ctx)
    out = graph.invoke({"brief": {"scene": SceneScript}, "candidates": [first_plan], "lenses": lenses(kit)})
    out["candidates"][out["winner"]]   the plan to use      out["notes"]    what the critics said (merged)
    out["results"]                     each critic's {lens, score, notes}, None for one that failed: the scores are for
                                       a person to read, they decide nothing

A candidate is an `AdamPlan` as data (aliases kept). The four critics run in parallel, each with its own lens; a
critic that fails is left out; with notes, ONE revision is made by the reviser, as operations on the plan, and
`adam_fidelity` drops any added moment that invents story before the revision is scored. A crowded card in the revision
is repaired by `adam_split` (code), so an overrun is never a reason to delete. The reviser must also answer every note
(plan/2026-11-04c F5): a revision whose dispositions do not hold up (a high note unanswered, an `add` that fills
nothing, a moment removed for no note) does not stand, and the first plan is kept with the reasons in its report.
`adam_score` (code) picks, a fidelity break, a required cell lost to the other candidate or an overrun losing first; a
revision replaces the first plan only when it is strictly better.

`evaluate(kit, scene, plan)` is the code's whole opinion of one plan (the reports and the score), for the caller's own
records.
"""
from __future__ import annotations

import threading
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from contracts.adam.plan import AdamPlan, ShotCard
from contracts.adam.screening import Noted, check_revision, drop_moments, remap_sound
from hiru_ai.core.context import RunContext
from hiru_ai.core.manifest import PanelManifest
from hiru_ai.core.panels import PanelKit
from hiru_ai.core.patterns import critics_judge
from hiru_ai.core.registry import Registry

ID = "adam_screening"
REPORTS = ("fidelity", "fit", "continuity", "feasibility", "coverage")


def lenses(kit: PanelKit) -> list[str]:
    return kit.names()


def dump(plan: AdamPlan) -> dict[str, Any]:
    return dict(plan.model_dump(mode="json", by_alias=True))


def evaluate(kit: PanelKit, scene: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """The code's reports on one plan and its craft score: `{"fidelity", "fit", "continuity", "feasibility", "coverage",
    "score", "rank"}`. A plan that cannot be read is a loss, never an exception."""
    base = {"scene": scene, "plan": plan}
    editorial = bool((plan.get("report") or {}).get("editorial"))  # the production trims takes: runtimes count use_s
    found = {}
    for name in REPORTS:
        asked = {**base, "editorial": editorial} if name == "fit" else base
        found[name] = kit.step(f"step:adam_{name}", "step").run(asked)
    score = kit.step(kit.manifest.judge, "step").run({**base, **found})
    return {**found, "score": score, "rank": kit.step(kit.manifest.judge).rank(score)}


def operations_of(answer: Any, revised: Any) -> list[dict[str, Any]]:
    """The reviser's operations as a record: what each did, to what, the note it answered and whether it applied."""
    named = {n: d.note_id for d in answer.dispositions for n in d.done}
    rows = []
    for n, op in enumerate(answer.operations, start=1):
        target = op.id if op.op == "remove_moment" else (op.moment.id if op.op == "add_moment" and op.moment
                                                         else op.number)
        rows.append({"n": n, "op": op.op, "why": op.why, "target": target, "applied": bool(revised.applied[n - 1]),
                     "note_id": named.get(n, "")})
    return rows


def ledger_of(said: list[Noted], answer: Any) -> list[dict[str, Any]]:
    """Every note with what became of it: the operations that answered it, why it was declined, or nothing."""
    by_note = {d.note_id: d for d in answer.dispositions}
    rows = []
    for note in said:
        d = by_note.get(note.id)
        rows.append({"id": note.id, "lens": note.lens, "severity": note.severity, "kind": note.kind,
                     "card": note.card, "cell": note.cell, "note": note.note,
                     "done": list(d.done) if d else [], "declined": d.declined.strip() if d else "",
                     "answered": bool(d and (d.done or d.declined.strip()))})
    return rows


def build(ctx: RunContext | None = None, registry: Registry | None = None,
          manifest: PanelManifest | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    kit = PanelKit(ID, ctx, registry, manifest)
    notes = kit.step("step:adam_notes", "step")
    fidelity = kit.step("step:adam_fidelity", "step")
    split = kit.step("step:adam_split", "step")
    coverage = kit.step("step:adam_coverage", "step")
    reviser_id = kit.role("reviser")[1] if kit.has("reviser") else ""
    cache: dict[int, dict[str, Any]] = {}  # each candidate's evaluation, made once for everyone who wants it
    lock = threading.Lock()
    judge = kit.step(kit.manifest.judge)

    def eval_of(state: dict[str, Any], index: int = 0) -> dict[str, Any]:
        with lock:
            if index not in cache:
                cache[index] = evaluate(kit, state["brief"]["scene"], state["candidates"][index])
            return cache[index]

    def first_eval(state: dict[str, Any]) -> dict[str, Any]:
        return eval_of(state, 0)

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
        scene = state["brief"]["scene"]
        said = [Noted.of(r) for r in notes.run({"results": state.get("results") or []})["kept"]]
        report = notes.run({**{k: found[k] for k in REPORTS}, "score": found["score"]})["text"]
        answer = kit.agent(reviser_id).run(screen_input(state, report=report, notes=lines), kit.ctx)
        revised = answer.apply(first.moments, first.cards)
        moments, cards = revised.moments, revised.cards
        numbers = dict(revised.renumbered)
        # An added moment that invents story is dropped here, so the revision is scored on what it may keep.
        check = fidelity.run({"scene": scene, "moments": [m.model_dump(mode="json") for m in moments]})
        if check["dropped"]:
            moments, cards, again = drop_moments(moments, cards, set(check["dropped"]))
            numbers = {old: again[new] for old, new in numbers.items() if new in again}
        # A crowded card is repaired in code, so an overrun is never a reason for the revision to delete (F4).
        mended = split.run({"scene": scene, "moments": [m.model_dump(mode="json", by_alias=True) for m in moments],
                            "cards": [c.model_dump(mode="json", by_alias=True) for c in cards],
                            "treatment": first.model_dump(mode="json", by_alias=True)["treatment"]})
        if mended["changed"]:
            cards = [ShotCard.model_validate(c) for c in mended["cards"]]
            numbers = {old: mended["renumbered"][new] for old, new in numbers.items() if new in mended["renumbered"]}
        sound = remap_sound(first.sound_map, numbers, {m.id for m in moments})
        plan = first.model_copy(update={"moments": moments, "cards": cards, "sound_map": sound})
        after = coverage.run({"scene": scene, "plan": dump(plan)})
        reasons = check_revision(
            said, answer, revised, filled={c["id"] for c in after["cells"] if c["ok"]},
            known={c["id"] for c in [*found["coverage"]["cells"], *after["cells"]]},
            first_kinds={m.kind for m in first.moments if m.tier != "script"},
            now_kinds={m.kind for m in moments if m.tier != "script"})
        record = {"operations": len(answer.operations), "skipped": revised.skipped, "dropped": check["dropped"],
                  "ops": operations_of(answer, revised), "ledger": ledger_of(said, answer),
                  "splits": mended["splits"], "unsplit": mended["unsplit"], "invalid": reasons}
        if reasons:  # the revision does not stand: the first plan is kept, with the reasons in its report
            return dump(first.model_copy(update={"report": {**first.report, "revision": record}}))
        return dump(plan.model_copy(update={"report": {**first.report, "revision": record}}))

    def score(candidate: Any, state: dict[str, Any]) -> Any:
        """Fewer breaks, then fewer required cells lost to the other candidate, then fewer overruns, then craft."""
        candidates = state["candidates"]
        index = next(i for i, c in enumerate(candidates) if c is candidate)
        results = [eval_of(state, i)["score"] for i in range(len(candidates))]
        return judge.rank(results[index], judge.lost_cells(results)[index])

    return critics_judge(critic, merged, revise if reviser_id else None, score)


def blank(registry: Registry | None = None,
          manifest: PanelManifest | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    return build(registry=registry, manifest=manifest)
