"""structure_build: read → analyse → ask → architect → write → looks. Ported from `structure_build/engine/pipeline.py`.

`ask` is where the graph stops for people (the `human_gate` pattern). With a durable checkpointer it calls LangGraph's
`interrupt()`: the hop writes the open questions, sets the job to `waiting_input` and returns. The API re-sends the
hop once
every question is answered (`state.resume`), and the graph resumes inside `ask` with the answers, hours later and
in another
instance if need be. Without a durable checkpointer it cannot wait, so it takes each suggested answer and records the
question as `defaulted` for a person to review.

Re-delivery (Cloud Tasks) of an unfinished hop resumes from the last finished node. The thread id
(`<job>:structure`), the
node names and the state keys are the legacy graph's, so a hop begun by either engine can be finished by the other.

The model's drafts (the prose cut, the episode names, the looks) go through the `structure_draft` panel; every answer is
checked in code and a missing or failed model falls to the rules.
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from contracts.build import Agent, QuestionStatus, Stage
from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from contracts.production import ProductionSettings
from contracts.veo import ASPECT_RATIO, Orientation
from hiru_ai.core import llm, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.patterns import ask_node
from hiru_ai.core.registry import Registry
from hiru_ai.systems.structure_build import rules
from hiru_ai.systems.structure_build.state import State

_logger = logging.getLogger(__name__)
AGENT = Agent.ARCHITECT.value


def build(ctx: RunContext, payload: DispatchPayload, *, durable: bool, envelope_s: int, aspect_ratio: str,
          draft_looks: bool = True) -> Any:
    jobs, structure = ctx.need("jobs"), ctx.need("structure")
    canon_port, docs_port = ctx.need("canon"), ctx.need("docs")
    job_id, production_id = payload.job_id, payload.production_id
    assert production_id is not None
    analyse, prose = parts.step("structure_analyse"), parts.step("prose_cut")
    panel = parts.module("panel", "structure_draft", "graph").build(ctx)

    def drafts(jobs_: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The model's drafts, side by side, in job order (each is `ok` or marked for the rules)."""
        return list(panel.invoke({"items": jobs_})["outputs"]) if jobs_ else []

    def read(state: State) -> State:
        canon = canon_port.entities(production_id)
        docs = []
        for d in docs_port.documents(production_id):
            role = d.get("confirmed_role") or d.get("detected_role") or "other"
            if role in rules.PROSE_ROLES and d.get("text_path"):
                item = {"id": str(d["id"]), "filename": d["filename"], "role": role,
                        "text": docs_port.text(d["text_path"])}
                # A story written as prose (a bible with its episodes in it, a treatment) has no scene headings for the
                # parser; it becomes screenplay text first, whatever its role.
                todo = prose.to_cut(item["text"])
                if todo:
                    if llm.models_enabled():
                        answers = drafts([{"member": "prose", "key": str(s.number), "input": prose.cut_input(s, canon)}
                                          for s in todo])
                        cuts = []
                        for section, got in zip(todo, answers, strict=True):
                            scenes = [s.model_dump() for s in got["output"].scenes] if got["ok"] else []
                            trusted = got["ok"] and prose.trusted(section, scenes)
                            cuts.append((scenes, True, False) if trusted else (prose.by_rules(section), False, True))
                    else:
                        cuts = [(prose.by_rules(s), False, False) for s in todo]
                    converted = prose.assemble(todo, cuts)
                    docs.append({**item, "role": "script", "text": converted.text,
                                 "scene_seconds": converted.scene_seconds})
                    how = "by the model" if converted.by_model else "by rules"
                    jobs.event(job_id, JobEventType.AGENT_STEP,
                               {"text": f"{d['filename']} tells its episodes as prose. Cut episodes "
                                        f"{', '.join(map(str, converted.episodes))} into scenes {how}."}, agent=AGENT)
                    if converted.fallbacks:
                        jobs.event(job_id, JobEventType.WARNING,
                                   {"text": "The model's scenes for episode "
                                            f"{', '.join(map(str, converted.fallbacks))} did not keep every spoken "
                                            "line word for word, so they were cut by rules: one scene each, no "
                                            "places. Check them."}, agent=AGENT)
                elif role in ("script", "outline"):
                    docs.append(item)
            elif role in ("script", "outline"):
                jobs.event(job_id, JobEventType.WARNING,
                           {"text": f"{d['filename']} was read before this build step existed; re-ingest it "
                                    "to include it."}, agent=AGENT)
        return {"documents": docs, "canon": canon}

    def analyse_node(state: State) -> State:
        jobs.stage(job_id, Stage.EPISODES.value, "active")
        plan = analyse.analyse(state["documents"], state["canon"])
        if not any(d["role"] == "script" for d in state["documents"]):
            jobs.event(job_id, JobEventType.WARNING, {"text": "No scripts were found, so episodes come from the "
                                                              "outline only. Upload scripts to build scenes."},
                       agent=AGENT)
        # A question a person already answered in an earlier build is not asked again: keys are stable across builds
        # (document id, place name, speaker name).
        asked = {q["key"] for q in plan["questions"]}
        earlier = {r["key"]: r["answer"] for r in structure.earlier_answers(production_id)
                   if r["key"] in asked and r.get("answer")}
        if earlier:
            jobs.event(job_id, JobEventType.PROGRESS,
                       {"text": f"Reused {len(earlier)} answers from earlier builds"}, agent=AGENT)
        return {"plan": plan, "answers": earlier}

    gate = ask_node(durable=durable, default=analyse.default_answers)

    def ask(state: State) -> State:
        questions = state["plan"]["questions"]
        out = gate({"questions": questions, "answers": state.get("answers")})
        defaulted = set(out["defaulted"])
        if defaulted:  # no durable checkpointer: the suggested answer was taken, and a person can still review it
            structure.upsert_questions(rules.question_rows(
                job_id, production_id, [q for q in questions if q["key"] in defaulted],
                status=QuestionStatus.DEFAULTED, answers={k: out["answers"][k] for k in defaulted}))
        return {"answers": out["answers"]}

    def architect_node(state: State) -> State:
        built = analyse.apply_answers(state["plan"], state["answers"], state["canon"])
        n_eps = len(built["episodes"])
        jobs.stage(job_id, Stage.EPISODES.value, "done", f"{n_eps} episodes")
        jobs.stage(job_id, Stage.SCENES.value, "active")
        if llm.models_enabled():
            names = parts.step("episode_names")
            todo = [e for e in built["episodes"] if e["scenes"]]
            answers = drafts([{"member": "architect", "key": str(e["number"]), "input": names.input_for(e)}
                              for e in todo])
            for episode, got in zip(todo, answers, strict=True):
                if not got["ok"]:
                    continue  # a failed episode keeps the rule-made labels
                names.apply(episode, got["output"].synopsis, [s.model_dump() for s in got["output"].scenes])
                jobs.event(job_id, JobEventType.PROGRESS,
                           {"text": f"Episode {episode['number']:02d}: {len(episode['scenes'])} scenes named"},
                           agent=AGENT)
        return {"structure": built}

    def write_node(state: State) -> State:
        tool = parts.module("tool", "structure_write", "tool")
        wrote = tool.run(tool.Args(structure=state["structure"], envelope_s=envelope_s, aspect_ratio=aspect_ratio), ctx)
        text = f"{wrote.episodes} episodes and {wrote.scenes} scenes from the scripts."
        if wrote.kept_approved:
            text += f" {wrote.kept_approved} approved scenes were left as they are."
        jobs.event(job_id, JobEventType.AGENT_STEP, {"text": text}, agent=AGENT)
        if wrote.new_characters:
            jobs.event(job_id, JobEventType.WARNING,
                       {"text": f"Added to the canon as drafts: {', '.join(wrote.new_characters[:10])}"
                                + (" …" if len(wrote.new_characters) > 10 else "")}, agent=AGENT)
        jobs.stage(job_id, Stage.SCENES.value, "done", f"{wrote.scenes} scenes")
        return {"report": {"episodes": wrote.episodes, "scenes": wrote.scenes, "scene_ids": wrote.scene_ids,
                           "kept_approved": wrote.kept_approved, "new_characters": len(wrote.new_characters),
                           "deleted_scenes": wrote.removed_scenes}}

    def looks_node(state: State) -> State:
        """Draft looks from the cards' wardrobes, now that the episodes are known. An extra: a failure here is a
        warning,
        never a failed build."""
        report = dict(state.get("report") or {})
        if not draft_looks:
            return {}
        try:
            plan = parts.step("look_plan")
            episodes = max((int(e["number"]) for e in structure.episodes(production_id)), default=1)
            canon = canon_port.entities(production_id)
            with_looks = structure.entities_with_looks(production_id)
            asked: list[dict[str, Any]] = []
            wanted = plan.wanted(canon, with_looks)
            if wanted and llm.models_enabled():
                (got,) = drafts([{"member": "looks", "key": "all", "input": plan.characters_input(wanted, episodes)}])
                if got["ok"]:
                    asked = [look.model_dump(by_alias=True) for look in got["output"].looks]
            rows, names = plan.rows_for(wanted, plan.asked_from(asked, episodes) if wanted else {}, episodes,
                                        production_id=str(production_id), actor=str(payload.actor_user_id))
            structure.create_looks(rows)
        except Exception:
            _logger.warning("drafting looks failed", exc_info=True)
            jobs.event(job_id, JobEventType.WARNING,
                       {"text": "Looks could not be drafted from the wardrobes. Add them on each character's page."},
                       agent=Agent.CANON.value)
            return {}
        if rows:
            jobs.event(job_id, JobEventType.AGENT_STEP,
                       {"text": f"Drafted {len(rows)} looks for {len(names)} characters from their wardrobes "
                                "(drafts: make each sheet, then mark it ready)."}, agent=Agent.CANON.value)
        return {"report": {**report, "looks": len(rows)}}

    g: Any = StateGraph(State)
    for name, fn in (("read", read), ("analyse", analyse_node), ("ask", ask), ("architect", architect_node),
                     ("write", write_node), ("looks", looks_node)):
        g.add_node(name, fn)
    g.add_edge(START, "read")
    for before, after in (("read", "analyse"), ("analyse", "ask"), ("ask", "architect"), ("architect", "write"),
                          ("write", "looks")):
        g.add_edge(before, after)
    g.add_edge("looks", END)
    return g


def run(payload: DispatchPayload, ctx: RunContext, checkpointer: BaseCheckpointSaver[Any] | None = None, *,
        durable: bool = False) -> dict[str, Any]:
    jobs, structure = ctx.need("jobs"), ctx.need("structure")
    skip = jobs.check(payload)
    if skip:
        return {"skipped": skip}
    job_id, production_id = payload.job_id, payload.production_id
    assert production_id is not None
    jobs.set(job_id, JobStatus.RUNNING)
    production = ctx.need("scenes").production(production_id)
    if production is None:
        jobs.set(job_id, JobStatus.DONE, result={"skipped": "production deleted"})
        return {"skipped": "production deleted"}
    settings = ProductionSettings.model_validate(production.get("settings") or {})
    carry: dict[str, Any] = {"build": bool(payload.state.get("build"))}
    if carry["build"] and not settings.build.scenes:
        jobs.stage(job_id, Stage.SCENES.value, "done", "Skipped: scenes are not part of this build")
        result: dict[str, Any] = {"skipped": "scenes not requested"}
        jobs.finish(payload, result, {**carry, "scene_ids": []})
        return result

    saver = checkpointer or InMemorySaver()
    app = build(ctx, payload, durable=durable, envelope_s=settings.default_scene_envelope_s,
                aspect_ratio=ASPECT_RATIO[Orientation(production["orientation"])],
                draft_looks=not carry["build"] or settings.build.canon).compile(checkpointer=saver)
    config: Any = {"configurable": {"thread_id": f"{job_id}:structure"}}
    started = bool(app.get_state(config).next)
    if payload.resuming and started:
        final = app.invoke(Command(resume=rules.answered(structure.answers(job_id))), config)
    else:
        final = app.invoke(None if started else State(), config)

    interrupts = final.get("__interrupt__") or []
    if interrupts:
        questions = interrupts[0].value["questions"]
        structure.upsert_questions(rules.question_rows(job_id, production_id, questions, status=QuestionStatus.OPEN))
        jobs.set(job_id, JobStatus.WAITING_INPUT)
        jobs.event(job_id, JobEventType.QUESTION, {"text": f"{len(questions)} questions need an answer",
                                                   "count": len(questions)}, agent=AGENT)
        return {"waiting": len(questions)}

    report = dict(final.get("report") or {})
    carry["scene_ids"] = [] if not settings.build.shots else report.get("scene_ids", [])
    result = {k: v for k, v in report.items() if k != "scene_ids"}
    jobs.finish(payload, result, carry)
    saver.delete_thread(config["configurable"]["thread_id"])
    return result


def blank(registry: Registry | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    """The graph with nothing to run, for drawing and for the generated contract tests."""
    from dataclasses import replace
    from uuid import uuid4

    from contracts.jobs import JobKind
    from hiru_ai.core.context import Ports
    from hiru_ai.core.fakes import FakeCanon, FakeDocs, FakeJobs, FakeScenes, FakeStructure

    payload = DispatchPayload(job_id=uuid4(), kind=JobKind.STRUCTURE_BUILD, actor_user_id=uuid4(),
                              production_id=uuid4())
    ports = replace(Ports(), jobs=FakeJobs(), structure=FakeStructure(), canon=FakeCanon(), docs=FakeDocs(),
                    scenes=FakeScenes())
    ctx = RunContext(production_id=payload.production_id, ports=ports)
    return build(ctx, payload, durable=False, envelope_s=45, aspect_ratio="16:9").compile()
