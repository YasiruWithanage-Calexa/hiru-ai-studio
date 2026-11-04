"""The structure_build system's own rules on the core fakes (the whole-service fixtures are tests/parity)."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver

from contracts.build import QuestionStatus
from contracts.jobs import DispatchPayload, JobKind
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.fakes import FakeCanon, FakeDocs, FakeJobs, FakeScenes, FakeStructure
from hiru_ai.systems.structure_build import graph, rules

CORPUS = Path(__file__).resolve().parents[6] / "tests" / "fixtures" / "corpus"
PID = uuid4()
QUESTIONABLE = "INT. KAMALA'S HOUSE - NIGHT\n\nNIMAL\nOK.\n\nEXT. KALUGALA BEACH - DAY\n\nWaves.\n"


def setup(text: str = QUESTIONABLE,
          settings: dict[str, Any] | None = None) -> tuple[RunContext, FakeJobs, FakeStructure]:
    docs = FakeDocs([{"id": "d1", "filename": "untitled.txt", "confirmed_role": "script", "detected_role": None,
                      "text_path": "p/d1.txt", "production_id": str(PID)}], {"p/d1.txt": text})
    structure, jobs = FakeStructure(), FakeJobs(status="running", cursor=1)
    scenes = FakeScenes(production={"id": str(PID), "orientation": "horizontal", "settings": settings or {}})
    ports = replace(Ports(), jobs=jobs, docs=docs, canon=FakeCanon(), structure=structure, scenes=scenes)
    return RunContext(production_id=PID, ports=ports), jobs, structure


def payload(job_id: Any = None, *, resume: bool = False) -> DispatchPayload:
    pipeline = [JobKind.CANON_EXTRACT, JobKind.STRUCTURE_BUILD, JobKind.SCRIPT_SPLIT]
    return DispatchPayload(job_id=job_id or uuid4(), kind=JobKind.STRUCTURE_BUILD, actor_user_id=uuid4(),
                           production_id=PID, pipeline=pipeline, cursor=1,
                           state={"build": True, **({"resume": True} if resume else {})})


def test_a_question_stops_the_hop_and_keeps_its_checkpoint_for_the_resume():
    ctx, jobs, structure = setup()
    saver, p = InMemorySaver(), payload()
    assert graph.run(p, ctx, saver, durable=True) == {"waiting": 1}
    assert jobs.status == "waiting_input" and {q["status"] for q in structure.question_rows.values()} == {"open"}
    assert list(saver.list({"configurable": {"thread_id": f"{p.job_id}:structure"}}))  # the legacy thread name


def test_without_a_durable_checkpointer_the_suggested_answer_is_taken_and_recorded():
    ctx, jobs, structure = setup()
    result = graph.run(payload(), ctx, InMemorySaver(), durable=False)
    assert "waiting" not in result and jobs.status != "waiting_input"
    assert {q["status"] for q in structure.question_rows.values()} == {QuestionStatus.DEFAULTED.value}


def test_a_finished_hop_deletes_its_checkpoint_and_hands_the_scenes_on():
    ctx, jobs, _ = setup((CORPUS / "harbour-lights-ep01-script.fountain").read_text(encoding="utf-8"))
    saver, p = InMemorySaver(), payload()
    result = graph.run(p, ctx, saver, durable=True)
    assert result["scenes"] > 0 and "scene_ids" not in result
    assert jobs.advanced and jobs.advanced[0]["state"]["scene_ids"]  # the next function reads these
    assert not list(saver.list({"configurable": {"thread_id": f"{p.job_id}:structure"}}))


def test_scenes_can_be_left_out_of_a_build():
    ctx, jobs, _ = setup(settings={"build": {"scenes": False}})
    assert graph.run(payload(), ctx, InMemorySaver(), durable=True) == {"skipped": "scenes not requested"}
    assert jobs.advanced[0]["state"]["scene_ids"] == []


def test_question_ids_are_stable_so_a_resume_finds_its_rows():
    job = uuid4()
    assert rules.question_id(job, "episode:d1:0") == rules.question_id(job, "episode:d1:0")
    assert rules.question_id(job, "a") != rules.question_id(uuid4(), "a")
    rows = [{"key": "k", "status": "answered", "answer": {"value": "1"}},
            {"key": "j", "status": "open", "answer": None}]
    assert rules.answered(rows) == {"k": {"value": "1"}}
