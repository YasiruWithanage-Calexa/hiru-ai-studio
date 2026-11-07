"""canon_extract: read → extract → dedupe → critic → write. Ported from `canon_extract/engine/pipeline.py`.

The first hop of the structure build, and a job of its own ("re-extract canon"). With a durable checkpointer a retried
delivery resumes at the node that failed instead of paying for the model calls again; the thread is deleted once the hop
is finished. The thread id and the node names are the legacy graph's, so a job started by either engine can be
finished by
the other.

Absent-safe: without a key the rules alone extract the canon (index codes, bible cards, script cues and headings)
and the
result is complete enough to build scenes against. A model that fails leaves the rules' canon (extract) or the list as
it is (dedupe).
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from contracts.build import Agent, Stage
from contracts.doc_read import reading_candidates
from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from contracts.production import ProductionSettings
from contracts.veo import ASPECT_RATIO, Orientation
from hiru_ai.core import agents, doc_reader, llm, parts, story
from hiru_ai.core.context import RunContext
from hiru_ai.core.registry import Registry
from hiru_ai.systems.canon_extract.state import State

_logger = logging.getLogger(__name__)
AGENT = Agent.CANON.value


def read_documents(ctx: RunContext, production_id: Any) -> tuple[list[dict[str, str]], list[str]]:
    """Ready documents with their extracted text. A document indexed before the text was kept (no `text_path`) is
    skipped with a warning: re-ingesting it fixes that."""
    docs_port = ctx.need("docs")
    docs, warnings = [], []
    for d in docs_port.documents(production_id):
        role = d.get("confirmed_role") or d.get("detected_role") or "other"
        if not d.get("text_path"):
            warnings.append(f"{d['filename']} was read before this build step existed; re-ingest it to include it.")
            continue
        item: dict[str, Any] = {"id": str(d["id"]), "filename": d["filename"], "role": role,
                                "text_path": d["text_path"], "text": docs_port.text(d["text_path"])}
        read = doc_reader.load(ctx, d)  # the document reader's reading (plan/2026-11-06f)
        if read is not None:
            item["reading"] = read.model_dump(mode="json")
        docs.append(item)
    return docs, warnings


def people_found(ctx: RunContext, documents: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Everyone the story reader found in the documents (read now if a document has no saved reading), once each."""
    found: dict[str, dict[str, Any]] = {}
    for d in documents:
        reading = story.story_for(ctx, d, d["text"])
        for p in (reading or {}).get("people", []):
            known = found.setdefault(p["name"].casefold(), {**p, "aliases": []})
            known["aliases"] = [*known["aliases"], *(a for a in p["aliases"] if a not in known["aliases"])]
            known["voice_only"] = bool(known["voice_only"] and p["voice_only"])
    return list(found.values())


def build(ctx: RunContext, payload: DispatchPayload, aspect_ratio: str) -> StateGraph[Any, Any, Any, Any]:
    jobs = ctx.need("jobs")
    job_id, production_id = payload.job_id, payload.production_id
    assert production_id is not None
    merge = parts.step("canon_merge")

    def read(state: State) -> State:
        jobs.stage(job_id, Stage.READ.value, "active")
        docs, warnings = read_documents(ctx, production_id)
        roles = sorted({d["role"] for d in docs})
        jobs.event(job_id, JobEventType.AGENT_STEP,
                   {"text": f"Read {len(docs)} files ({', '.join(roles) or 'none'})."}, agent=Agent.INGESTION.value)
        for w in warnings:
            jobs.event(job_id, JobEventType.WARNING, {"text": w}, agent=Agent.INGESTION.value)
        jobs.stage(job_id, Stage.READ.value, "done", f"{len(docs)} files")
        return {"documents": docs, "warnings": warnings}

    def extract(state: State) -> State:
        jobs.stage(job_id, Stage.CANON.value, "active")
        canon_rules = parts.module("step", "canon_rules", "step")
        found = reading_candidates(state["documents"], rule_candidates=canon_rules.rule_candidates,
                                   merge=canon_rules.rules.merge, same=canon_rules.rules.same)
        if found is not None:  # the reader already mapped every cue to a person: no extraction, no dedupe
            jobs.event(job_id, JobEventType.AGENT_STEP,
                       {"text": "Canon from the document reader's readings; codes from the documents."}, agent=AGENT)
            return {"candidates": found, "read": True}
        cands = canon_rules.rule_candidates(state["documents"])
        if llm.models_enabled():
            try:
                told = merge.counts(cands)
                out = agents.build("canon_extractor").run(
                    {"documents": state["documents"], "people": people_found(ctx, state["documents"]), **told}, ctx)
                cands = merge.combine(cands, merge.from_answer([e.model_dump() for e in out.entities]))
            except Exception:
                _logger.warning("model extraction failed; keeping the rules' canon", exc_info=True)
        return {"candidates": cands}

    def dedupe(state: State) -> State:
        cands = state["candidates"]
        if llm.models_enabled() and len(cands) > 1 and not state.get("read"):
            try:
                out = agents.build("canon_deduper").run({"candidates": merge.dedupe_input(cands)}, ctx)
                cands = merge.apply_groups(cands, [g.model_dump() for g in out.groups])
            except Exception:
                _logger.warning("dedupe failed; keeping the list as it is", exc_info=True)
        return {"candidates": cands}

    def critic(state: State) -> State:
        return {"notes": parts.module("step", "canon_rules", "step").critic(state["candidates"])}

    def write_node(state: State) -> State:
        cands = state["candidates"]
        tool = parts.module("tool", "canon_write", "tool")
        wrote = tool.run(tool.Args(candidates=cands, aspect_ratio=aspect_ratio), ctx)
        report = {"created": wrote.created, "versioned": wrote.versioned, "updated": wrote.updated,
                  "unchanged": wrote.unchanged, "locked": wrote.locked, "notes": state.get("notes", [])}
        text = "Canon drafted from the documents. All items are drafts until you approve them."
        if wrote.locked:
            text += f" Locked items were left as they are ({', '.join(wrote.locked)})."
        jobs.event(job_id, JobEventType.AGENT_STEP,
                   {"text": text, "chips": parts.module("step", "canon_rules", "step").chips(cands)}, agent=AGENT)
        for note in state.get("notes", []):
            jobs.event(job_id, JobEventType.WARNING, {"text": note}, agent=AGENT)
        jobs.stage(job_id, Stage.CANON.value, "done", f"{len(cands)} items")
        return {"report": report}

    g: Any = StateGraph(State)
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


def run(payload: DispatchPayload, ctx: RunContext, checkpointer: BaseCheckpointSaver[Any] | None = None
        ) -> dict[str, Any]:
    jobs = ctx.need("jobs")
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
    carry = {"build": bool(payload.state.get("build"))}
    if carry["build"] and not settings.build.canon:
        jobs.stage(job_id, Stage.CANON.value, "done", "Skipped: canon is not part of this build")
        result: dict[str, Any] = {"skipped": "canon not requested"}
        jobs.finish(payload, result, carry)
        return result

    saver = checkpointer or InMemorySaver()
    aspect = ASPECT_RATIO[Orientation(production["orientation"])]
    app = build(ctx, payload, aspect).compile(checkpointer=saver)
    config: Any = {"configurable": {"thread_id": f"{job_id}:canon"}}
    started = bool(app.get_state(config).next)  # a retry: carry on from the last finished node
    final = app.invoke(None if started else State(), config)
    result = dict(final.get("report") or {})
    jobs.finish(payload, result, carry)
    saver.delete_thread(config["configurable"]["thread_id"])
    return result


def blank(registry: Registry | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    """The graph with nothing to run, for drawing and for the generated contract tests."""
    from dataclasses import replace
    from uuid import uuid4

    from contracts.jobs import JobKind
    from hiru_ai.core.context import Ports
    from hiru_ai.core.fakes import FakeJobs

    payload = DispatchPayload(job_id=uuid4(), kind=JobKind.CANON_EXTRACT, actor_user_id=uuid4(),
                              production_id=uuid4())
    ctx = RunContext(production_id=payload.production_id, ports=replace(Ports(), jobs=FakeJobs()))
    return build(ctx, payload, "16:9").compile()
