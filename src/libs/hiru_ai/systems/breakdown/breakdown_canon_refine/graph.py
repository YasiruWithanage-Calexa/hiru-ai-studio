"""breakdown_canon_refine: real canon cards and scene looks from the finished breakdown (plan/2026-11-12c §3.2).

    load    the breakdown memory, the documents' numbered lines and the canon as it is now (the versions READ, so the
            write can refuse a card a person changed since)
    canon   `breakdown_canon` (split by `contracts.canon_refine.parts` when big), code checks, ONE repair call for the
            failed ids alone
    looks   `breakdown_looks` over the refined cast (split by episode when big, each part given the looks before it),
            code checks, ONE repair call
    apply   `canon_refine_apply` (schema v23): all at once; a locked or person-written card gets a proposal (D2)

A production without a breakdown (D4) gets the looks alone, from today's scenes and canon cards; its cards need the
breakdown ("Rebuild with the breakdown first"). Run as its own job (`JobKind.CANON_REFINE`, served by the canon_extract
function) or, through `refine_calls` and `apply`, as the branch of `breakdown_build` that runs beside fill (phase 7).
Never half-written: the write is one transaction, and a failed call leaves the canon as it was.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from contracts import canon_refine as cr
from contracts import scene_looks as sl
from contracts.breakdown import memory as bmem
from contracts.breakdown.schema import Breakdown, SourceMemory
from contracts.build import Agent
from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from contracts.veo import ASPECT_RATIO, Orientation
from hiru_ai.core import agents, llm
from hiru_ai.core.context import RunContext
from hiru_ai.core.registry import Registry
from hiru_ai.systems.breakdown.breakdown_canon_refine.state import State

_log = logging.getLogger(__name__)
AGENT = Agent.CANON.value
Row = dict[str, Any]
KEPT = "Canon kept as extracted"
NO_MODEL = "Refining the canon needs the AI model, which is not available. The canon is as it was."


@dataclass
class Calls:
    canon: Callable[[str], cr.Answer]
    looks: Callable[[str], sl.LooksAnswer]


def calls(ctx: RunContext) -> Calls:
    canon, looks = agents.build("breakdown_canon"), agents.build("breakdown_looks")
    return Calls(
        canon=lambda m: canon.run({"message": m}, ctx),
        looks=lambda m: looks.run({"message": m}, ctx),
    )


@dataclass
class Result:
    """What one refine produced: the payload for the write, and what the person reads (no costs, ever)."""

    payload: Row = field(default_factory=dict)
    review: list[str] = field(default_factory=list)  # review findings and fixes the repair could not mend
    notes: list[str] = field(default_factory=list)  # warnings for the job's events
    story: list[Row] = field(default_factory=list)  # story time per scene, for the review list
    refined: int = 0


def _say(progress: Callable[[str], None] | None, text: str) -> None:
    if progress is not None:
        progress(text)


def canon_answer(
    bd: Breakdown,
    lines: list[str],
    canon: list[Row],
    call: Callable[[str], cr.Answer],
    progress: Callable[[str], None] | None = None,
) -> tuple[cr.Answer, list[cr.Finding]]:
    """The canon call (split when big), the checks and one repair for the failed ids. Returns what the checks still
    say."""
    ids = bd.canon_ids or None
    answers: list[cr.Answer] = []
    groups = cr.parts(bd, lines, canon, canon_ids=ids)
    for n, group in enumerate(groups, 1):
        if len(groups) > 1:
            _say(progress, f"Canon cards, part {n} of {len(groups)}")
        message = cr.message(bd, lines, canon, group, ids)
        answer = call(message)
        found = cr.fixes(cr.check(answer, bd, lines, group))
        if found:
            _say(progress, f"Mending {len({f.id for f in found})} cards the checks refused")
            try:
                answer = cr.merge(answer, call(cr.repair_message(message, answer, found)))
            except Exception:  # a failed repair keeps the first answer; the findings are reported
                _log.warning("the canon repair call failed", exc_info=True)
        answers.append(answer)
    answer = cr.join(answers)
    return answer, cr.check(answer, bd, lines)


def looks_answer(
    data: Row, truth: sl.Truth, call: Callable[[str], sl.LooksAnswer], progress: Callable[[str], None] | None = None
) -> tuple[sl.LooksAnswer, list[sl.Finding]]:
    answers: list[sl.LooksAnswer] = []
    carried: list[sl.Look] = []
    pieces = sl.parts(data)
    for n, part in enumerate(pieces, 1):
        if len(pieces) > 1:
            _say(progress, f"Looks, part {n} of {len(pieces)}")
        message = sl.message(part, carried)
        ids = [s["id"] for s in part["scenes"]]
        answer = call(message)
        fixes = [f for f in sl.check(answer, ids, truth, carried) if f.level == "fix"]
        if fixes:
            _say(progress, f"Mending {len(fixes)} things the looks checks refused")
            try:
                answer = call(sl.repair_message(message, answer, fixes))
            except Exception:
                _log.warning("the looks repair call failed", exc_info=True)
        answers.append(answer)
        carried = [*carried, *(lk for lk in answer.looks if lk.id not in {c.id for c in carried})]
    joined = sl.join(answers)
    return joined, sl.check(joined, [s["id"] for s in data["scenes"]], truth)


@dataclass
class Answers:
    """The two calls' checked answers, before anything is mapped to rows: the build's refine branch makes them while
    fill writes the canon, and maps them only after the join (a fresh build's canon entities do not exist before)."""

    canon: cr.Answer
    looks: sl.LooksAnswer | None = None
    review: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def dump(self) -> Row:
        return {"canon": self.canon.model_dump(), "looks": self.looks.model_dump() if self.looks else None,
                "review": self.review, "notes": self.notes}

    @classmethod
    def load(cls, row: Row) -> Answers:
        looks = row.get("looks")
        return cls(canon=cr.Answer.model_validate(row["canon"]),
                   looks=sl.LooksAnswer.model_validate(looks) if looks else None,
                   review=list(row.get("review") or []), notes=list(row.get("notes") or []))


def answers(
    bd: Breakdown,
    lines: list[str],
    canon: list[Row],
    *,
    calls: Calls,
    progress: Callable[[str], None] | None = None,
) -> Answers:
    """Both calls and their checks; nothing is written or mapped. A failed canon call raises (nothing to write); a
    failed looks call leaves the cards and says so."""
    _say(progress, "Writing the canon cards from the breakdown")
    answer, found = canon_answer(bd, lines, canon, calls.canon, progress)
    out = Answers(canon=answer, review=[f.message for f in found])
    try:
        _say(progress, "Deciding what everyone wears, scene by scene")
        data, truth = sl.from_breakdown(bd, answer)
        out.looks, lfound = looks_answer(data, truth, calls.looks, progress)
        out.review += [f.message for f in lfound]
    except Exception as exc:  # the cards stand without the looks
        _log.warning("the looks call failed", exc_info=True)
        out.notes.append(f"Looks were not drafted ({type(exc).__name__}); the cards are refined.")
    return out


def payload_of(ans: Answers, bd: Breakdown, canon: list[Row], *, aspect_ratio: str, actor: str | None) -> Result:
    """The answers mapped to the canon AS IT IS NOW (the versions read, the scene rows fill wrote)."""
    ids = bd.canon_ids or None
    a = ans.canon
    out = Result(refined=len(a.people) + len(a.places) + len(a.things), review=list(ans.review), notes=list(ans.notes))
    versions = cr.versions(a, bd, canon, aspect_ratio=aspect_ratio, actor=actor, canon_ids=ids)
    looks: list[Row] = []
    scene_looks: list[Row] = []
    if ans.looks is not None:
        _, truth = sl.from_breakdown(bd, a)
        rows = {s.id: s.row_id for s in bd.scenes if s.row_id}
        looks, scene_looks = sl.rows(ans.looks, truth, cr.canon_map(bd, canon, ids), rows)
        out.story = [s.model_dump() for s in ans.looks.story]
    out.payload = {"actor": actor, "versions": versions, "looks": looks, "scene_looks": scene_looks}
    return out


def refine_calls(
    bd: Breakdown,
    lines: list[str],
    canon: list[Row],
    *,
    calls: Calls,
    aspect_ratio: str,
    actor: str | None,
    progress: Callable[[str], None] | None = None,
) -> Result:
    """The standalone job's refine: both calls, then the payload against the canon read before them."""
    return payload_of(answers(bd, lines, canon, calls=calls, progress=progress), bd, canon,
                      aspect_ratio=aspect_ratio, actor=actor)


def looks_from_tables(
    ctx: RunContext,
    production_id: UUID,
    canon: list[Row],
    *,
    calls: Calls,
    actor: str | None,
    progress: Callable[[str], None] | None = None,
) -> Result:
    """D4: a production built before the breakdown. The looks alone, from today's scenes and canon cards."""
    scenes_port = ctx.need("scenes")
    rows = scenes_port.scenes(production_id, None)
    episodes: dict[int, Row] = {}
    scenes, lines, key_to_row = [], {}, {}
    for s in rows:
        ep = s.get("episode") or {}
        number = int(ep.get("number") or 1)
        episodes.setdefault(
            number, {"number": number, "title": ep.get("title") or "", "synopsis": ep.get("synopsis") or ""}
        )
        key = sl.scene_key(number, int(s.get("number") or 0))
        key_to_row[key] = str(s["id"])
        place = next((c["name"] for c in canon if str(c["id"]) == str(s.get("location_id") or "")), "")
        scenes.append(
            {
                "key": key,
                "episode": number,
                "heading": str((s.get("heading") or {}).get("raw") or "")
                if isinstance(s.get("heading"), dict)
                else str(s.get("heading") or ""),
                "title": s.get("title") or "",
                "place": place,
                "script": s.get("script") or [],
            }
        )
        lines[key] = scenes_port.lines(str(s["id"]))
    scenes.sort(key=lambda x: x["key"])
    people = [
        {"code": c["code"], "name": c["name"], "card": (c.get("current") or {}).get("card") or {}}
        for c in canon
        if c["kind"] == "character"
    ]
    data, truth = sl.from_tables([episodes[k] for k in sorted(episodes)], scenes, lines, people)
    _say(progress, "Deciding what everyone wears, scene by scene")
    la, found = looks_answer(data, truth, calls.looks, progress)
    entity_of = {c["code"]: str(c["id"]) for c in canon if c["kind"] == "character"}
    looks, scene_looks = sl.rows(la, truth, entity_of, key_to_row)
    return Result(
        payload={"actor": actor, "versions": [], "looks": looks, "scene_looks": scene_looks},
        review=[f.message for f in found],
        notes=[
            "Canon cards need the breakdown: rebuild with the breakdown first. Looks were drafted from today's scenes."
        ],
        story=[s.model_dump() for s in la.story],
    )


def apply(ctx: RunContext, production_id: UUID, res: Result) -> Row:
    """The one write. Returns the counts and the review list for the job's result."""
    counts = ctx.need("canon").refine_apply(production_id, res.payload)
    return {**counts, "refined": res.refined, "review": res.review[:60], "story": res.story}


def lines_of(bd: Breakdown, sources: list[SourceMemory]) -> list[str]:
    return bmem.doc(sources, bd.person_lines).lines


def summary(report: Row) -> str:
    bits = [f"{report.get('switched', 0)} cards refined"]
    if report.get("proposed"):
        bits.append(f"{report['proposed']} proposals for locked or hand-written cards")
    if report.get("skipped_changed"):
        bits.append(f"{report['skipped_changed']} changed by a person since, left alone")
    if report.get("looks"):
        bits.append(f"{report['looks']} draft looks")
    if report.get("review"):
        bits.append(f"{len(report['review'])} things to review")
    return "; ".join(bits) + "."


# ── the job ────────────────────────────────────────────────────────────────────────────────────────────────────────


def build(
    ctx: RunContext,
    payload: DispatchPayload,
    *,
    aspect_ratio: str = "16:9",
    make_calls: Callable[[RunContext], Calls] = calls,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    jobs = ctx.need("jobs")
    job_id, production_id = payload.job_id, payload.production_id
    assert production_id is not None
    actor = str(payload.actor_user_id) if payload.actor_user_id else None

    def say(text: str) -> None:
        jobs.event(job_id, JobEventType.PROGRESS, {"text": text}, agent=AGENT)

    holder: dict[str, Result] = {}

    def load(state: State) -> State:
        store = ctx.ports.breakdown
        row = store.memory(production_id) if store is not None else None
        return {"has_breakdown": bool(row)}

    def refine(state: State) -> State:
        canon = ctx.need("canon").entities(production_id)
        try:
            if state.get("has_breakdown"):
                store = ctx.need("breakdown")
                row = store.memory(production_id) or {}
                bd = Breakdown.model_validate(row["body"])
                sources = [SourceMemory.model_validate(r["body"]) for r in store.sources(production_id)]
                res = refine_calls(
                    bd,
                    lines_of(bd, sources),
                    canon,
                    calls=make_calls(ctx),
                    aspect_ratio=aspect_ratio,
                    actor=actor,
                    progress=say,
                )
            else:
                res = looks_from_tables(ctx, production_id, canon, calls=make_calls(ctx), actor=actor, progress=say)
        except Exception as exc:
            _log.warning("canon refine failed", exc_info=True)
            return {"failed": f"The canon could not be refined ({type(exc).__name__}). The canon is as it was."}
        holder["res"] = res
        for note in res.notes:
            jobs.event(job_id, JobEventType.WARNING, {"text": note}, agent=AGENT)
        return {}

    def write(state: State) -> State:
        if state.get("failed"):
            return {}
        try:
            report = apply(ctx, production_id, holder["res"])
        except Exception as exc:
            _log.warning("canon_refine_apply failed", exc_info=True)
            return {
                "failed": f"The refined canon could not be saved ({type(exc).__name__}): is schema v23 applied? "
                "The canon is as it was."
            }
        jobs.event(job_id, JobEventType.AGENT_STEP, {"text": summary(report)}, agent=AGENT)
        return {"report": report}

    g: Any = StateGraph(State)
    for name, fn in (("load", load), ("refine", refine), ("apply", write)):
        g.add_node(name, fn)
    g.add_edge(START, "load")
    g.add_edge("load", "refine")
    g.add_edge("refine", "apply")
    g.add_edge("apply", END)
    return g.compile()


def run(payload: DispatchPayload, ctx: RunContext, make_calls: Callable[[RunContext], Calls] = calls) -> Row:
    jobs = ctx.need("jobs")
    skip = jobs.check(payload)
    if skip:
        return {"skipped": skip}
    job_id, production_id = payload.job_id, payload.production_id
    assert production_id is not None
    jobs.set(job_id, JobStatus.RUNNING)
    if not llm.models_enabled():
        jobs.set(job_id, JobStatus.FAILED, error=NO_MODEL)
        return {"failed": NO_MODEL}
    production = ctx.need("scenes").production(production_id)
    if production is None:
        jobs.set(job_id, JobStatus.DONE, result={"skipped": "production deleted"})
        return {"skipped": "production deleted"}
    orientation = production.get("orientation")
    app = build(
        ctx,
        payload,
        aspect_ratio=ASPECT_RATIO[Orientation(orientation)] if orientation else "16:9",
        make_calls=make_calls,
    )
    final = app.invoke(State())
    if final.get("failed"):
        jobs.set(job_id, JobStatus.FAILED, error=final["failed"])
        return {"failed": final["failed"]}
    result = dict(final.get("report") or {})
    jobs.finish(payload, result)
    return result


def blank(registry: Registry | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    """The graph with nothing to run, for drawing and for the generated contract tests."""
    from dataclasses import replace

    from contracts.jobs import JobKind
    from hiru_ai.core.context import Ports
    from hiru_ai.core.fakes import FakeBreakdown, FakeCanon, FakeJobs, FakeScenes

    payload = DispatchPayload(job_id=uuid4(), kind=JobKind.CANON_REFINE, actor_user_id=uuid4(), production_id=uuid4())
    ports = replace(Ports(), jobs=FakeJobs(), canon=FakeCanon(), scenes=FakeScenes(), breakdown=FakeBreakdown())
    return build(RunContext(production_id=payload.production_id, ports=ports), payload)
