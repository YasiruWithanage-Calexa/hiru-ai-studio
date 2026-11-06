"""doc_ingest: one document, start to finish: download → extract → role → story → memory → chunk → headers → embed →
index.
Ported from `doc_ingest/engine/pipeline.py`; the steps and agents are found by id.

Outcomes, each written to the document row:
  ready     indexed. With no OpenAI key, or if embedding fails, it is still indexed for keyword search and says so in
            `warnings`; re-ingest later to add meaning search.
  rejected  the FILE is unusable as given (a scanned PDF, not UTF-8 ...). The job itself is DONE: it did its work, and a
            retry would reject it again.
  failed    OUR failure (an exception). The handler marks the job and the document failed; re-ingest can fix it.

Idempotent for Cloud Tasks re-delivery: a finished job is skipped, chunks are replaced (not appended), and embeddings
are reused by hash so a re-run does not pay for them twice. A model that is missing or fails never stops the ingest:
the rules' role and the base headers stand.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from contracts.documents import DocumentStatus
from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from hiru_ai.core import agents, llm, memory, parts, story
from hiru_ai.core.context import RunContext
from hiru_ai.core.registry import Registry
from hiru_ai.core.settings import get_settings
from hiru_ai.rag.embeddings import embed_texts
from hiru_ai.systems.doc_ingest import rules
from hiru_ai.systems.doc_ingest.state import State

_logger = logging.getLogger(__name__)


def build(ctx: RunContext, payload: DispatchPayload,
          document: dict[str, Any]) -> CompiledStateGraph[Any, Any, Any, Any]:
    jobs, docs, files = ctx.need("jobs"), ctx.need("docs"), ctx.need("files")
    job_id = payload.job_id
    document_id = UUID(str(payload.state["document_id"]))
    filename = document["filename"]

    def progress(text: str, **extra: Any) -> None:
        jobs.event(job_id, JobEventType.PROGRESS, {"text": text, "document_id": str(document_id), **extra},
                   agent=rules.AGENT)

    def read(state: State) -> State:
        extract = parts.step("extract_text")
        progress(f"Reading {filename}")
        data = files.download(rules.BUCKET, document["storage_path"])
        try:
            found = extract.extract(data, filename, document["mime_type"])
        except extract.Rejected as rejected:
            docs.update_document(document_id, {"status": DocumentStatus.REJECTED.value, "error": str(rejected),
                                               "chunk_count": 0})
            docs.replace_chunks(document_id, [])
            return {"rejected": True, "result": {"document_id": str(document_id), "status": "rejected",
                                                 "reason": str(rejected)}}
        extracted = {"kind": found.kind, "lines": [{"text": ln.text, "page": ln.page} for ln in found.lines],
                     "page_count": found.page_count, "char_count": found.char_count,
                     "has_sinhala": found.has_sinhala}
        text_path = f"{document['production_id']}/{document_id}/extracted.txt"
        files.upload(rules.BUCKET, text_path, rules.paged_text(extracted["lines"]).encode("utf-8"),
                     "text/plain; charset=utf-8")
        return {"extracted": extracted, "text": found.text, "text_path": text_path, "rejected": False}

    def role(state: State) -> State:
        roles = parts.step("document_role")
        guess = roles.detect_by_rules(filename, state["text"])
        verdict = {"role": guess.role.value, "confidence": guess.confidence, "reason": guess.reason,
                   "source": guess.source}
        if guess.confidence < roles.LLM_THRESHOLD and llm.models_enabled():
            try:  # the model is asked only when the rules are unsure; a failing call keeps the rules
                out = agents.build("role_classifier").run({"filename": filename, "text": state["text"]}, ctx)
                verdict = {"role": out.role, "confidence": out.confidence, "reason": out.reason, "source": "model"}
            except Exception:
                _logger.warning("role model failed; keeping the rules' guess", exc_info=True)
        chosen = str(document["confirmed_role"]) if document.get("confirmed_role") else verdict["role"]
        label = parts.step("chunk_headers").ROLE_LABEL[verdict["role"]]
        progress(f"{filename} looks like a {label}", role=verdict["role"], confidence=verdict["confidence"])
        return {"guess": verdict, "role": chosen}

    def story_node(state: State) -> State:
        """Read the document once for its story (episodes, spoken lines, people) and keep the checked reading beside
        the text. An extra: a model that is missing or fails leaves no `story.json` and the ingest goes on."""
        if not llm.models_enabled():
            return {}
        try:
            reading = story.read(ctx, filename, state["text"])
            if reading is None:
                return {}
            story.save(ctx, state["text_path"], reading)
        except Exception:
            _logger.warning("story reading failed; continuing without it", exc_info=True)
            return {}
        lines = sum(len(e["spoken"]) for e in reading["episodes"])
        progress(f"Read the story in {filename}: {len(reading['episodes'])} episodes, {lines} spoken lines, "
                 f"{len(reading['people'])} people")
        for text in reading["warnings"]:
            jobs.event(job_id, JobEventType.WARNING, {"text": f"{filename}: {text}", "document_id": str(document_id)},
                       agent=rules.AGENT)
        return {}

    def memory_node(state: State) -> State:
        """Read the document once for the direction it gives about how to make the drama (plan/2026-11-05d) and keep
        the checked entries as the document's reader drafts. An extra, like the story: with no model, no memory port or
        no table (the migration is not applied yet) nothing is asked, and a failure leaves the document's earlier
        entries as they are and the ingest goes on."""
        port = ctx.ports.memory
        if port is None or not llm.models_enabled():
            return {}
        production_id = UUID(str(document["production_id"]))
        try:
            port.entries(production_id)  # the table must be there before a model call is paid for
        except Exception:
            _logger.warning("production memory is not available; the direction of %s is not read", filename,
                            exc_info=True)
            return {}
        try:
            found = memory.read(ctx, filename, state["text"])
            if found is None:
                return {}
            port.replace_from(production_id, document_id, found["entries"])
        except Exception:
            _logger.warning("production memory not kept for %s", filename, exc_info=True)
            jobs.event(job_id, JobEventType.WARNING,
                       {"text": f"{filename}: the direction it gives could not be kept",
                        "document_id": str(document_id)},
                       agent=rules.AGENT)
            return {}
        progress(f"Read the direction in {filename}: {len(found['entries'])} entries")
        for text in found["warnings"]:
            jobs.event(job_id, JobEventType.WARNING, {"text": f"{filename}: {text}", "document_id": str(document_id)},
                       agent=rules.AGENT)
        every = port.entries(production_id)
        mine = {str(r["id"]) for r in every if str(r.get("document_id")) == str(document_id)}
        for conflict in memory.conflicts(ctx, every):
            if mine & {str(i) for i in conflict["ids"]}:  # only what this document is part of
                jobs.event(job_id, JobEventType.WARNING, {"text": conflict["text"], "document_id": str(document_id)},
                           agent=rules.AGENT)
        return {}

    def chunk(state: State) -> State:
        split = parts.step("chunk")
        lines = [split.Line(ln["text"], ln["page"]) for ln in state["extracted"]["lines"]]
        made = split.chunk(split.Extracted(state["extracted"]["kind"], lines), script_like=state["role"] == "script")
        progress(f"Split into {len(made)} passages")
        return {"chunks": [asdict(c) for c in made]}

    def headers(state: State) -> State:
        text = parts.step("chunk_headers")
        chunks = state["chunks"]
        answers: list[list[dict[str, Any]] | None] = []
        if llm.models_enabled() and chunks:
            for batch in text.batches(chunks):
                try:  # the document prefix is identical for every batch (the prompt cache); the batch comes last
                    out = agents.build("chunk_contextualiser").run(
                        {"filename": filename, "role": state["role"], "overview": state["text"],
                         "passages": [{"ord": c["ord"], "heading": c["heading"], "content": c["content"]}
                                      for c in batch]}, ctx)
                    answers.append([h.model_dump() for h in out.headers])
                except Exception:
                    _logger.warning("header batch failed; keeping base headers", exc_info=True)
                    answers.append(None)
        made = parts.module("step", "chunk_headers", "step").run(
            {"filename": filename, "role": state["role"], "chunks": chunks, "answers": answers})
        warnings = []
        if (w := rules.legacy_font_warning(state["extracted"], state["role"])) is not None:
            warnings.append(w)
        return {"headers": made["headers"], "warnings": warnings}

    def embed(state: State) -> State:
        text = parts.step("chunk_headers")
        model = get_settings().openai.embedding_model
        chunks, warnings = state["chunks"], list(state["warnings"])
        inputs = {c["ord"]: text.embedding_input(state["headers"][str(c["ord"])], c["content"]) for c in chunks}
        hashes = {o: rules.embed_hash(model, t) for o, t in inputs.items()}
        vectors: dict[int, list[float]] = {}
        if llm.models_enabled():
            reuse = docs.existing_embeddings(document_id)
            for o, h in hashes.items():
                if h in reuse and reuse[h][1] == model:
                    vectors[o] = reuse[h][0]
            todo = [o for o in inputs if o not in vectors]
            try:
                made = embed_texts([inputs[o] for o in todo], "doc_ingest.embed", ctx.sink(), batch=rules.EMBED_BATCH)
                for o, vec in zip(todo, made, strict=True):
                    if vec is None:
                        raise RuntimeError("the embedding model did not answer")
                    vectors[o] = vec
                progress(f"Embedded {len(todo)} passages ({len(inputs) - len(todo)} reused)")
            except Exception:
                _logger.exception("embedding failed document=%s", document_id)
                vectors = {}
                warnings.append(rules.EMBED_FAILED_WARNING)
        else:
            warnings.append(rules.NO_KEY_WARNING)
        return {"vectors": vectors, "hashes": hashes, "warnings": warnings, "embedding_model": model}

    def index(state: State) -> State:
        rows = rules.chunk_rows(document, str(document_id), state["chunks"], state["headers"], state["hashes"],
                                state["vectors"], state["embedding_model"])
        docs.replace_chunks(document_id, rows)
        guess, extracted = state["guess"], state["extracted"]
        docs.update_document(document_id, {
            "status": DocumentStatus.READY.value,
            "detected_role": guess["role"],
            "role_confidence": guess["confidence"],
            "role_reason": f"{guess['reason']} ({guess['source']})",
            "page_count": extracted["page_count"],
            "char_count": extracted["char_count"],
            "chunk_count": len(rows),
            "text_path": state["text_path"],
            "warnings": state["warnings"],
            "error": None,
        })
        return {"result": {"document_id": str(document_id), "status": "ready", "role": guess["role"],
                           "chunks": len(rows), "embedded": len(state["vectors"])}}

    g: Any = StateGraph(State)
    for name, node in (("read", read), ("role", role), ("story", story_node), ("memory", memory_node),
                       ("chunk", chunk),
                       ("headers", headers), ("embed", embed), ("index", index)):
        g.add_node(name, node)
    g.add_edge(START, "read")
    g.add_conditional_edges("read", lambda state: END if state.get("rejected") else "role", ["role", END])
    for before, after in (("role", "story"), ("story", "memory"), ("memory", "chunk"), ("chunk", "headers"),
                          ("headers", "embed"), ("embed", "index")):
        g.add_edge(before, after)
    g.add_edge("index", END)
    return g.compile()


def run(payload: DispatchPayload, ctx: RunContext) -> dict[str, Any]:
    jobs, docs = ctx.need("jobs"), ctx.need("docs")
    skip = jobs.check(payload)
    if skip:
        return {"skipped": skip}
    document_id = UUID(str(payload.state["document_id"]))
    document = docs.get_document(document_id)
    if document is None:  # deleted while queued
        jobs.set(payload.job_id, JobStatus.DONE, result={"skipped": "document deleted"})
        return {"skipped": "document deleted"}
    jobs.set(payload.job_id, JobStatus.RUNNING)
    docs.update_document(document_id, {"status": DocumentStatus.PROCESSING.value, "error": None})
    result: dict[str, Any] = build(ctx, payload, document).invoke({})["result"]
    jobs.set(payload.job_id, JobStatus.DONE, result=result)
    return result


def blank(registry: Registry | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    """The graph with nothing to run, for drawing and for the generated contract tests."""
    from dataclasses import replace
    from uuid import uuid4

    from contracts.jobs import JobKind
    from hiru_ai.core.context import Ports
    from hiru_ai.core.fakes import FakeDocs, FakeFiles, FakeJobs

    ports = replace(Ports(), jobs=FakeJobs(), docs=FakeDocs(), files=FakeFiles())
    payload = DispatchPayload(job_id=uuid4(), kind=JobKind.DOC_INGEST, actor_user_id=uuid4(),
                              state={"document_id": str(uuid4())})
    return build(RunContext(ports=ports), payload,
                 {"id": str(uuid4()), "filename": "x", "storage_path": "p", "mime_type": "text/plain",
                  "production_id": str(uuid4())})
