"""The structure build as a LangGraph: read → analyse → ask → architect → write (PLAN.md §2.2).

`ask` is where the graph stops for people. With a durable checkpointer it calls LangGraph's
`interrupt()`: the hop writes the open questions, sets the job to `waiting_input` and returns.
The API re-sends the hop once every question is answered (`state.resume`), and the graph
resumes inside `ask` with the answers, hours later and in another instance if need be. Without a
durable checkpointer it cannot wait, so it takes each suggested answer and records the question
as `defaulted` for a person to review.

Re-delivery (Cloud Tasks) of an unfinished hop resumes from the last finished node.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Protocol, TypedDict
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from contracts.build import Agent, QuestionStatus, Stage
from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from contracts.production import ProductionSettings
from contracts.veo import ASPECT_RATIO, Orientation
from structure_build.engine import analyse, architect, write

_logger = logging.getLogger(__name__)
AGENT = Agent.ARCHITECT.value
QUESTION_NS = uuid.UUID("6f1c2b0e-3d7a-4c55-9a51-8f6f0e2a7b10")


class StoreLike(Protocol):
    def production(self, production_id: UUID) -> dict[str, Any] | None: ...
    def documents(self, production_id: UUID) -> list[dict[str, Any]]: ...
    def text(self, path: str) -> str: ...
    def canon(self, production_id: UUID) -> list[dict[str, Any]]: ...
    def create_entity(self, entity: dict[str, Any], version: dict[str, Any]) -> None: ...
    def episodes(self, production_id: UUID) -> list[dict[str, Any]]: ...
    def upsert_episodes(self, rows: list[dict[str, Any]]) -> None: ...
    def scenes(self, production_id: UUID) -> list[dict[str, Any]]: ...
    def write_scene(self, scene: dict[str, Any], lines: list[dict[str, Any]]) -> None: ...
    def delete_scenes(self, scene_ids: list[str]) -> None: ...
    def upsert_questions(self, rows: list[dict[str, Any]]) -> None: ...
    def answers(self, job_id: UUID) -> list[dict[str, Any]]: ...
    def earlier_answers(self, production_id: UUID) -> list[dict[str, Any]]: ...


class JobsLike(Protocol):
    def check(self, payload: DispatchPayload) -> str | None: ...
    def set(self, job_id: UUID, status: JobStatus, **fields: Any) -> None: ...
    def event(self, job_id: UUID, type_: JobEventType, payload: dict[str, Any], agent: str | None = None) -> None: ...
    def stage(self, job_id: UUID, stage: str, state: str, text: str = "") -> None: ...
    def finish(self, payload: DispatchPayload, result: dict[str, Any],
               next_state: dict[str, Any] | None = None) -> None: ...


class LLMLike(Protocol):
    @property
    def enabled(self) -> bool: ...
    def json(self, *, tier: str, phase: str, system: str, user: str, schema_name: str,
             schema: dict[str, Any]) -> dict[str, Any]: ...


class State(TypedDict, total=False):
    documents: list[dict[str, str]]
    canon: list[dict[str, Any]]
    plan: dict[str, Any]
    answers: dict[str, dict[str, Any]]
    structure: dict[str, Any]
    report: dict[str, Any]


def question_id(job_id: UUID, key: str) -> str:
    return str(uuid.uuid5(QUESTION_NS, f"{job_id}:{key}"))


def question_rows(job_id: UUID, production_id: UUID, questions: list[dict[str, Any]], *,
                  status: QuestionStatus, answers: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    return [{"id": question_id(job_id, q["key"]), "production_id": str(production_id), "job_id": str(job_id),
             "key": q["key"][:300], "agent": q["agent"], "scope": q["scope"][:200], "title": q["title"][:200],
             "body": q["body"][:2000], "options": q["options"], "allow_text": q["allow_text"],
             "status": status.value, "answer": (answers or {}).get(q["key"])} for q in questions]


def build_graph(payload: DispatchPayload, store: StoreLike, jobs: JobsLike, llm: LLMLike, *,
                durable: bool, envelope_s: int, aspect_ratio: str) -> StateGraph[State]:
    job_id = payload.job_id
    production_id = payload.production_id
    assert production_id is not None

    def read(state: State) -> State:
        docs = []
        for d in store.documents(production_id):
            role = d.get("confirmed_role") or d.get("detected_role") or "other"
            if role in ("script", "outline") and d.get("text_path"):
                docs.append({"id": str(d["id"]), "filename": d["filename"], "role": role,
                             "text": store.text(d["text_path"])})
            elif role in ("script", "outline"):
                jobs.event(job_id, JobEventType.WARNING,
                           {"text": f"{d['filename']} was read before this build step existed; re-ingest it "
                                    "to include it."}, agent=AGENT)
        return {"documents": docs, "canon": store.canon(production_id)}

    def analyse_node(state: State) -> State:
        jobs.stage(job_id, Stage.EPISODES.value, "active")
        plan = analyse.analyse(state["documents"], state["canon"])
        if not any(d["role"] == "script" for d in state["documents"]):
            jobs.event(job_id, JobEventType.WARNING, {"text": "No scripts were found, so episodes come from the "
                                                              "outline only. Upload scripts to build scenes."},
                       agent=AGENT)
        # A question a person already answered in an earlier build is not asked again: keys are
        # stable across builds (document id, place name, speaker name).
        asked = {q["key"] for q in plan["questions"]}
        earlier = {r["key"]: r["answer"] for r in store.earlier_answers(production_id)
                   if r["key"] in asked and r.get("answer")}
        if earlier:
            jobs.event(job_id, JobEventType.PROGRESS,
                       {"text": f"Reused {len(earlier)} answers from earlier builds"}, agent=AGENT)
        return {"plan": plan, "answers": earlier}

    def ask(state: State) -> State:
        questions = state["plan"]["questions"]
        answers = dict(state.get("answers") or {})
        pending = [q for q in questions if q["key"] not in answers]
        if not pending:
            return {"answers": answers}
        if durable:
            given = interrupt({"questions": pending})  # the hop returns here; resumes with answers
            answers.update(given or {})
        defaults = analyse.default_answers([q for q in pending if q["key"] not in answers])
        if defaults:
            store.upsert_questions(question_rows(job_id, production_id,
                                                 [q for q in pending if q["key"] in defaults],
                                                 status=QuestionStatus.DEFAULTED, answers=defaults))
            answers.update(defaults)
        return {"answers": answers}

    def architect_node(state: State) -> State:
        structure = analyse.apply_answers(state["plan"], state["answers"], state["canon"])
        n_eps = len(structure["episodes"])
        jobs.stage(job_id, Stage.EPISODES.value, "done", f"{n_eps} episodes")
        jobs.stage(job_id, Stage.SCENES.value, "active")
        if llm.enabled:
            def ask_model(system: str, user: str) -> dict[str, Any]:
                return llm.json(tier="ultra", phase="structure_build.architect", system=system, user=user,
                                schema_name="episode_names", schema=architect.SCHEMA)

            def named(ep: dict[str, Any]) -> None:
                jobs.event(job_id, JobEventType.PROGRESS,
                           {"text": f"Episode {ep['number']:02d}: {len(ep['scenes'])} scenes named"}, agent=AGENT)

            architect.name_all(ask_model, structure["episodes"], named)
        return {"structure": structure}

    def write_node(state: State) -> State:
        p = write.plan(state["structure"], production_id=str(production_id), canon=store.canon(production_id),
                       existing_episodes=store.episodes(production_id), existing_scenes=store.scenes(production_id),
                       envelope_s=envelope_s, aspect_ratio=aspect_ratio, actor=str(payload.actor_user_id))
        for entity, version in p.entities:
            store.create_entity(entity, version)
        if p.episodes:
            store.upsert_episodes(p.episodes)
        for scene, lines in p.scenes:
            store.write_scene(scene, lines)
        store.delete_scenes(p.delete_scene_ids)
        n_scenes = len(p.scenes)
        text = f"{len(p.episodes)} episodes and {n_scenes} scenes from the scripts."
        if p.kept_approved:
            text += f" {p.kept_approved} approved scenes were left as they are."
        jobs.event(job_id, JobEventType.AGENT_STEP, {"text": text}, agent=AGENT)
        if p.new_characters:
            jobs.event(job_id, JobEventType.WARNING,
                       {"text": f"Added to the canon as drafts: {', '.join(p.new_characters[:10])}"
                                + (" …" if len(p.new_characters) > 10 else "")}, agent=AGENT)
        jobs.stage(job_id, Stage.SCENES.value, "done", f"{n_scenes} scenes")
        return {"report": {"episodes": len(p.episodes), "scenes": n_scenes, "scene_ids": p.scene_ids,
                           "kept_approved": p.kept_approved, "new_characters": len(p.new_characters),
                           "deleted_scenes": len(p.delete_scene_ids)}}

    g: StateGraph[State] = StateGraph(State)
    for name, fn in (("read", read), ("analyse", analyse_node), ("ask", ask), ("architect", architect_node),
                     ("write", write_node)):
        g.add_node(name, fn)
    g.add_edge(START, "read")
    g.add_edge("read", "analyse")
    g.add_edge("analyse", "ask")
    g.add_edge("ask", "architect")
    g.add_edge("architect", "write")
    g.add_edge("write", END)
    return g


def _answers(store: StoreLike, job_id: UUID) -> dict[str, dict[str, Any]]:
    return {r["key"]: r["answer"] for r in store.answers(job_id)
            if r["status"] == QuestionStatus.ANSWERED and r.get("answer")}


def run(payload: DispatchPayload, store: StoreLike, jobs: JobsLike, llm: LLMLike,
        checkpointer: BaseCheckpointSaver[Any], *, durable: bool) -> dict[str, Any]:
    skip = jobs.check(payload)
    if skip:
        return {"skipped": skip}
    job_id, production_id = payload.job_id, payload.production_id
    assert production_id is not None
    jobs.set(job_id, JobStatus.RUNNING)
    production = store.production(production_id)
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

    app = build_graph(payload, store, jobs, llm, durable=durable, envelope_s=settings.default_scene_envelope_s,
                      aspect_ratio=ASPECT_RATIO[Orientation(production["orientation"])]).compile(
        checkpointer=checkpointer)
    config: Any = {"configurable": {"thread_id": f"{job_id}:structure"}}
    started = bool(app.get_state(config).next)
    if payload.resuming and started:
        final = app.invoke(Command(resume=_answers(store, job_id)), config)
    else:
        final = app.invoke(None if started else State(), config)

    interrupts = final.get("__interrupt__") or []
    if interrupts:
        questions = interrupts[0].value["questions"]
        store.upsert_questions(question_rows(job_id, production_id, questions, status=QuestionStatus.OPEN))
        jobs.set(job_id, JobStatus.WAITING_INPUT)
        jobs.event(job_id, JobEventType.QUESTION, {"text": f"{len(questions)} questions need an answer",
                                                   "count": len(questions)}, agent=AGENT)
        return {"waiting": len(questions)}

    report = dict(final.get("report") or {})
    if not settings.build.shots:
        carry["scene_ids"] = []
    else:
        carry["scene_ids"] = report.get("scene_ids", [])
    result = {k: v for k, v in report.items() if k != "scene_ids"}
    jobs.finish(payload, result, carry)
    checkpointer.delete_thread(config["configurable"]["thread_id"])
    return result
