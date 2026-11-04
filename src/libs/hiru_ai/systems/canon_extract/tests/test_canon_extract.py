"""The canon_extract system on the core fakes (the whole-service fixtures are tests/parity)."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver

from contracts.jobs import DispatchPayload, JobKind
from hiru_ai.core import llm
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.fakes import FakeCanon, FakeDocs, FakeJobs, FakeScenes
from hiru_ai.core.testing import RoutedChatModel
from hiru_ai.systems.canon_extract import graph

CORPUS = Path(__file__).resolve().parents[6] / "tests" / "fixtures" / "corpus"
PID = uuid4()


def setup(settings: dict | None = None, *, with_production: bool = True) -> tuple[RunContext, FakeJobs, FakeCanon]:
    text = (CORPUS / "harbour-lights-ep01-script.fountain").read_text(encoding="utf-8")
    docs = FakeDocs([{"id": "d1", "filename": "ep1.fountain", "confirmed_role": "script", "detected_role": None,
                      "text_path": "p/d1.txt", "production_id": str(PID)},
                     {"id": "d2", "filename": "old.md", "confirmed_role": "bible", "detected_role": None,
                      "text_path": None, "production_id": str(PID)}], {"p/d1.txt": text})
    canon, jobs = FakeCanon(), FakeJobs()
    production = {"id": str(PID), "orientation": "horizontal", "settings": settings or {}} if with_production else None
    scenes = FakeScenes(production=production)
    ports = replace(Ports(), jobs=jobs, docs=docs, canon=canon, scenes=scenes)
    return RunContext(production_id=PID, ports=ports), jobs, canon


def payload(build: bool = False) -> DispatchPayload:
    return DispatchPayload(job_id=uuid4(), kind=JobKind.CANON_EXTRACT, actor_user_id=uuid4(), production_id=PID,
                           pipeline=[JobKind.CANON_EXTRACT], state={"build": build})


def test_without_a_key_the_rules_draft_the_canon_from_the_scripts():
    ctx, jobs, canon = setup()
    result = graph.run(payload(), ctx, InMemorySaver())
    assert result["created"] > 0 and result["locked"] == [] and jobs.status == "done"
    assert any("was read before this build step existed" in e.get("text", "") for e in jobs.events)  # old.md skipped
    assert {e["kind"] for e in canon.entity_rows} >= {"character", "location"}


def test_a_second_run_changes_nothing():
    ctx, jobs, _ = setup()
    graph.run(payload(), ctx, InMemorySaver())
    jobs.status = "pending"  # a new job
    again = graph.run(payload(), ctx, InMemorySaver())
    assert again["created"] == 0 and again["versioned"] == 0


def test_a_build_without_canon_is_skipped_and_handed_on():
    ctx, _, _ = setup({"build": {"canon": False}})
    assert graph.run(payload(build=True), ctx, InMemorySaver()) == {"skipped": "canon not requested"}


def test_a_production_deleted_while_queued_finishes_the_job():
    ctx, jobs, _ = setup(with_production=False)
    assert graph.run(payload(), ctx, InMemorySaver()) == {"skipped": "production deleted"} and jobs.status == "done"


def test_a_model_that_fails_leaves_the_rules_canon():
    ctx, _, canon = setup()
    with llm.use_models(RoutedChatModel(routes={})):  # every call raises
        result = graph.run(payload(), ctx, InMemorySaver())
    assert result["created"] > 0 and canon.entity_rows


def test_the_checkpoint_thread_is_the_legacy_one_and_is_deleted_at_the_end():
    ctx, _, _ = setup()
    saver = InMemorySaver()
    p = payload()
    graph.run(p, ctx, saver)
    assert not list(saver.list({"configurable": {"thread_id": f"{p.job_id}:canon"}}))
