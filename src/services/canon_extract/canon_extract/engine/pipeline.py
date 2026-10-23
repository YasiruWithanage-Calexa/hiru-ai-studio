"""Canon extraction as a LangGraph: read → extract → dedupe → critic → write (PLAN.md §2.2).

The first hop of the structure build, and a job of its own ("re-extract canon"). With a durable
checkpointer a retried delivery resumes at the node that failed instead of paying for the model
calls again; the thread is deleted once the hop is finished.

Absent-safe: without a key the rules alone extract the canon (index codes, bible cards, script
cues and headings) and the result is complete enough to build scenes against.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol, TypedDict
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from canon_extract.engine import model, rules, write
from contracts.build import Agent, Stage
from contracts.canon import CanonKind
from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from contracts.production import ProductionSettings
from contracts.screenplay import parse_document
from contracts.veo import ASPECT_RATIO, Orientation

_logger = logging.getLogger(__name__)
AGENT = Agent.CANON.value
SCRIPT, INDEX, BIBLE = "script", "canon_index", "bible"


class StoreLike(Protocol):
    def production(self, production_id: UUID) -> dict[str, Any] | None: ...
    def documents(self, production_id: UUID) -> list[dict[str, Any]]: ...
    def text(self, path: str) -> str: ...
    def entities(self, production_id: UUID) -> list[dict[str, Any]]: ...
    def create_entity(self, entity: dict[str, Any], version: dict[str, Any]) -> None: ...
    def add_version(self, entity_id: str, version: dict[str, Any], fields: dict[str, Any]) -> None: ...
    def update_entity(self, entity_id: str, fields: dict[str, Any]) -> None: ...


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
    candidates: list[dict[str, Any]]
    notes: list[str]
    warnings: list[str]
    report: dict[str, Any]


def read_documents(store: StoreLike, production_id: UUID) -> tuple[list[dict[str, str]], list[str]]:
    """Ready documents with their extracted text. A document indexed before the text was kept
    (no `text_path`) is skipped with a warning: re-ingesting it fixes that."""
    docs, warnings = [], []
    for d in store.documents(production_id):
        role = d.get("confirmed_role") or d.get("detected_role") or "other"
        if not d.get("text_path"):
            warnings.append(f"{d['filename']} was read before this build step existed; re-ingest it to include it.")
            continue
        docs.append({"id": str(d["id"]), "filename": d["filename"], "role": role, "text": store.text(d["text_path"])})
    return docs, warnings


def rule_candidates(documents: list[dict[str, str]]) -> list[rules.Candidate]:
    index = [c for d in documents if d["role"] == INDEX for c in rules.from_index(d["text"], d["filename"])]
    bible = [c for d in documents if d["role"] == BIBLE for c in rules.from_bible(d["text"], d["filename"])]
    known = {n for c in [*index, *bible] for n in [c["name"], *c["aliases"]]}
    parsed = [(d["filename"], parse_document(d["text"], d["filename"], known))
              for d in documents if d["role"] == SCRIPT]
    return rules.drop_uncertain_places(rules.merge(index, bible, rules.from_scripts(parsed)))


def chips(cands: list[rules.Candidate]) -> list[str]:
    chars = [c for c in cands if c["kind"] == CanonKind.CHARACTER]
    core = sum(1 for c in chars if c["core"])
    out = [f"{core} core characters", f"{len(chars) - core} supporting",
           f"{sum(1 for c in cands if c['kind'] == CanonKind.LOCATION)} locations",
           f"{sum(1 for c in cands if c['kind'] == CanonKind.PROP)} props"]
    return [c for c in out if not c.startswith("0 ")]


def build_graph(payload: DispatchPayload, store: StoreLike, jobs: JobsLike, llm: LLMLike,
                aspect_ratio: str) -> StateGraph[State]:
    job_id = payload.job_id
    production_id = payload.production_id
    assert production_id is not None

    def ask(tier: str, phase: str, name: str, schema: dict[str, Any]) -> model.Ask:
        return lambda system, user: llm.json(tier=tier, phase=phase, system=system, user=user,
                                             schema_name=name, schema=schema)

    def read(state: State) -> State:
        jobs.stage(job_id, Stage.READ.value, "active")
        docs, warnings = read_documents(store, production_id)
        roles = sorted({d["role"] for d in docs})
        jobs.event(job_id, JobEventType.AGENT_STEP,
                   {"text": f"Read {len(docs)} files ({', '.join(roles) or 'none'})."}, agent=Agent.INGESTION.value)
        for w in warnings:
            jobs.event(job_id, JobEventType.WARNING, {"text": w}, agent=Agent.INGESTION.value)
        jobs.stage(job_id, Stage.READ.value, "done", f"{len(docs)} files")
        return {"documents": docs, "warnings": warnings}

    def extract(state: State) -> State:
        jobs.stage(job_id, Stage.CANON.value, "active")
        cands = rule_candidates(state["documents"])
        if llm.enabled:
            try:
                found = model.extract(ask("high", "canon_extract.extract", "canon", model.EXTRACT_SCHEMA),
                                      state["documents"], cands)
                cands = model.combine(cands, found)
            except Exception:
                _logger.warning("model extraction failed; keeping the rules' canon", exc_info=True)
        return {"candidates": cands}

    def dedupe(state: State) -> State:
        cands = state["candidates"]
        if llm.enabled and len(cands) > 1:
            try:
                cands = model.dedupe(ask("medium", "canon_extract.dedupe", "canon_dupes", model.DEDUPE_SCHEMA), cands)
            except Exception:
                _logger.warning("dedupe failed; keeping the list as it is", exc_info=True)
        return {"candidates": cands}

    def critic(state: State) -> State:
        return {"notes": write.critic(state["candidates"])}

    def write_node(state: State) -> State:
        cands = state["candidates"]
        p = write.plan(cands, store.entities(production_id), production_id=str(production_id),
                       aspect_ratio=aspect_ratio, actor=str(payload.actor_user_id))
        for entity, version in p.creates:
            store.create_entity(entity, version)
        for entity_id, version, fields in p.versions:
            store.add_version(entity_id, version, fields)
        for entity_id, fields in p.updates:
            store.update_entity(entity_id, fields)
        report = {"created": len(p.creates), "versioned": len(p.versions), "updated": len(p.updates),
                  "unchanged": p.unchanged, "locked": p.locked, "notes": state.get("notes", [])}
        text = "Canon drafted from the documents. All items are drafts until you approve them."
        if p.locked:
            text += f" Locked items were left as they are ({', '.join(p.locked)})."
        jobs.event(job_id, JobEventType.AGENT_STEP, {"text": text, "chips": chips(cands)}, agent=AGENT)
        for note in state.get("notes", []):
            jobs.event(job_id, JobEventType.WARNING, {"text": note}, agent=AGENT)
        jobs.stage(job_id, Stage.CANON.value, "done", f"{len(cands)} items")
        return {"report": report}

    g: StateGraph[State] = StateGraph(State)
    for name, fn in (("read", read), ("extract", extract), ("dedupe", dedupe), ("critic", critic),
                     ("write", write_node)):
        g.add_node(name, fn)
    g.add_edge(START, "read")
    g.add_edge("read", "extract")
    g.add_edge("extract", "dedupe")
    g.add_edge("dedupe", "critic")
    g.add_edge("critic", "write")
    g.add_edge("write", END)
    return g


def run(payload: DispatchPayload, store: StoreLike, jobs: JobsLike, llm: LLMLike,
        checkpointer: BaseCheckpointSaver[Any]) -> dict[str, Any]:
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
    carry = {"build": bool(payload.state.get("build"))}
    if carry["build"] and not settings.build.canon:
        jobs.stage(job_id, Stage.CANON.value, "done", "Skipped: canon is not part of this build")
        result: dict[str, Any] = {"skipped": "canon not requested"}
        jobs.finish(payload, result, carry)
        return result

    aspect = ASPECT_RATIO[Orientation(production["orientation"])]
    app = build_graph(payload, store, jobs, llm, aspect).compile(checkpointer=checkpointer)
    config: Any = {"configurable": {"thread_id": f"{job_id}:canon"}}
    started = bool(app.get_state(config).next)  # a retry: carry on from the last finished node
    final = app.invoke(None if started else State(), config)
    result = dict(final.get("report") or {})
    jobs.finish(payload, result, carry)
    checkpointer.delete_thread(config["configurable"]["thread_id"])
    return result
