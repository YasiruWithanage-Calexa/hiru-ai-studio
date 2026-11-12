"""The canon refine system on fakes (plan/2026-11-12c phase 4): Ekama's breakdown with the lab's saved answers (run2,
looks1) through the real agents, the write all at once, a locked card as a proposal, a card a person changed since
the read left alone, a person's look kept, a re-run that changes nothing, and a failure that leaves the canon as it
was. No model, no network, no database."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from contracts.jobs import DispatchPayload, JobKind
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.fakes import FakeBreakdown, FakeCanon, FakeJobs, FakeScenes
from hiru_ai.core.llm import use_models
from hiru_ai.core.testing import ScriptedChatModel
from hiru_ai.systems.breakdown.breakdown_canon_refine import graph

PID = UUID("00000000-0000-0000-0000-0000000000cc")
FIX = Path(__file__).resolve().parents[7] / "tests" / "fixtures" / "canon_refine"


def _load(name: str) -> Any:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _world(breakdown: bool = True) -> tuple[RunContext, DispatchPayload, FakeCanon]:
    fx = _load("ekama.json")
    canon = FakeCanon()
    for c in fx["canon"]:
        cur = c["current"]
        canon.entity_rows.append(
            {k: c[k] for k in ("id", "kind", "code", "name", "aliases", "locked")}
            | {"production_id": str(PID), "current_version_id": cur["id"]}
        )
        canon.versions.append({**cur, "entity_id": c["id"], "card_hash": f"h-{c['code']}"})
    store = FakeBreakdown()
    if breakdown:
        store.memories[str(PID)] = {"body": fx["memory"], "version": 1}
        store.source_rows.append(
            {
                "production_id": str(PID),
                "document_id": "d1",
                "filename": "ekama.pdf",
                "body": {
                    "document_id": "d1",
                    "filename": "ekama.pdf",
                    "lines": fx["lines"],
                    "split": {"sections": [], "cards": [], "rules": [], "episodes": []},
                },
            }
        )
    ports = replace(
        Ports(),
        jobs=FakeJobs(),
        canon=canon,
        breakdown=store,
        scenes=FakeScenes({"id": str(PID), "orientation": "horizontal", "settings": {}}),
    )
    payload = DispatchPayload(job_id=uuid4(), kind=JobKind.CANON_REFINE, actor_user_id=uuid4(), production_id=PID)
    return RunContext(production_id=PID, ports=ports), payload, canon


def _current(canon: FakeCanon, code: str) -> dict[str, Any]:
    ent = next(e for e in canon.entity_rows if e["code"] == code)
    return next(v for v in canon.versions if v["id"] == ent["current_version_id"])


def _replies() -> list[Any]:
    return [_load("run2.json"), _load("looks1_ekama.json")]


def test_ekama_is_refined_and_the_locked_cast_gets_proposals() -> None:
    ctx, payload, canon = _world()
    with use_models(ScriptedChatModel(replies=_replies())):
        result = graph.run(payload, ctx)
    assert ctx.ports.jobs.status == "done"
    # Ekama: Dinu, Aruni, Nimal, Colombo, the canal, the van, the medical bag and the key are locked: proposals
    assert result["proposed"] == 8 and result["switched"] == 14 and result["skipped_changed"] == 0
    assert _current(canon, "C01")["source"] == "extract"  # locked: still the extracted card
    assert len([v for v in canon.versions if v["entity_id"] == _ent(canon, "C01")["id"]]) == 2  # + the proposal
    suren = _current(canon, "C05")
    assert suren["source"] == "refine" and suren["card"]["age"] == "38" and suren["provenance"]["age"]["line"] > 0
    garage = _current(canon, "L05")
    assert garage["card"]["summary"] == "" and "Nimal" not in garage["reference_prompt"]
    assert _ent(canon, "L06")["class"] == "spot" and _ent(canon, "L06")["parent_id"] == _ent(canon, "L03")["id"]
    assert _ent(canon, "P06")["class"] == "mentioned"
    assert result["looks"] > 0 and result["scene_looks"] > 0
    assert all(lk["status"] == "draft" and lk["origin"] == "refine" for lk in canon.look_rows)
    assert result["story"] and "cards refined" in " ".join(ctx.ports.jobs.texts())


def _ent(canon: FakeCanon, code: str) -> dict[str, Any]:
    return next(e for e in canon.entity_rows if e["code"] == code)


def test_a_card_a_person_changed_since_the_read_is_left_alone() -> None:
    ctx, payload, canon = _world()
    real = canon.refine_apply

    def person_edits_first(production_id: UUID, body: dict[str, Any]) -> dict[str, Any]:
        suren = _ent(canon, "C05")
        canon.versions.append(
            {"id": "v-person", "entity_id": suren["id"], "version": 2, "card": {}, "source": "user", "card_hash": "p"}
        )
        suren["current_version_id"] = "v-person"
        return real(production_id, body)

    canon.refine_apply = person_edits_first  # type: ignore[method-assign]
    with use_models(ScriptedChatModel(replies=_replies())):
        result = graph.run(payload, ctx)
    assert result["skipped_changed"] == 1 and _ent(canon, "C05")["current_version_id"] == "v-person"


def test_a_person_s_look_and_scene_look_are_kept() -> None:
    ctx, payload, canon = _world()
    dinu = _ent(canon, "C01")
    looks = _load("looks1_ekama.json")
    name = next(lk["name"] for lk in looks["looks"] if lk["person"] == "C01")
    canon.look_rows.append(
        {
            "id": "mine",
            "entity_id": dinu["id"],
            "name": name,
            "outfit": "a red shirt",
            "status": "ready",
            "origin": "person",
        }
    )
    with use_models(ScriptedChatModel(replies=_replies())):
        graph.run(payload, ctx)
    assert next(lk for lk in canon.look_rows if lk["id"] == "mine")["outfit"] == "a red shirt"
    assert len([lk for lk in canon.look_rows if lk["entity_id"] == dinu["id"] and lk["name"] == name]) == 1


def test_a_re_run_with_the_same_answer_changes_nothing() -> None:
    ctx, payload, canon = _world()
    with use_models(ScriptedChatModel(replies=_replies())):
        graph.run(payload, ctx)
    versions, looks = len(canon.versions), len(canon.look_rows)
    ctx2 = replace(ctx, ports=replace(ctx.ports, jobs=FakeJobs()))
    with use_models(ScriptedChatModel(replies=_replies())):
        again = graph.run(payload.model_copy(update={"job_id": uuid4()}), ctx2)
    assert again["switched"] == 0 and again["looks"] == 0 and again["unchanged"] == 14
    assert (len(canon.versions), len(canon.look_rows)) == (versions, looks)


def test_a_failed_call_leaves_the_canon_as_it_was() -> None:
    ctx, payload, canon = _world()
    before = [dict(e) for e in canon.entity_rows], len(canon.versions)
    with use_models(ScriptedChatModel(replies=[])):
        result = graph.run(payload, ctx)
    assert "could not be refined" in result["failed"] and ctx.ports.jobs.status == "failed"
    assert ([dict(e) for e in canon.entity_rows], len(canon.versions)) == before


def test_a_missing_write_function_fails_the_job_and_writes_nothing() -> None:
    ctx, payload, canon = _world()
    canon.broken = RuntimeError("function canon_refine_apply does not exist")
    with use_models(ScriptedChatModel(replies=_replies())):
        result = graph.run(payload, ctx)
    assert "schema v23" in result["failed"] and all(v["source"] != "refine" for v in canon.versions)


def test_a_failed_looks_call_keeps_the_cards() -> None:
    ctx, payload, _ = _world()
    with use_models(ScriptedChatModel(replies=[_load("run2.json")])):
        result = graph.run(payload, ctx)
    assert result["switched"] == 14 and result["looks"] == 0
    assert any("Looks were not drafted" in t for t in ctx.ports.jobs.texts("warning"))


def test_without_a_breakdown_only_looks_are_drafted() -> None:
    ctx, payload, _ = _world(breakdown=False)
    scenes = ctx.ports.scenes
    scenes.scene_rows.append(
        {
            "id": "s1",
            "production_id": str(PID),
            "number": 1,
            "heading": "EXT. CANAL - DAWN",
            "title": "",
            "location_id": None,
            "episode": {"number": 1, "title": "", "synopsis": ""},
            "script": [{"kind": "action", "text": "Dinu waits."}],
        }
    )
    reply = {
        "story": [{"scene": "E01-S01", "story_day": 1, "part_of_day": "dawn", "continuous_with": "", "why": "x"}],
        "looks": [
            {
                "id": "C01-1",
                "person": "C01",
                "name": "Work",
                "outfit": "a navy shirt",
                "hair": "",
                "makeup": "",
                "accessories": "",
                "why": "x",
            }
        ],
        "scenes": [
            {"scene": "E01-S01", "on_screen": [{"person": "C01", "look": "C01-1", "condition": "", "why": "x"}]}
        ],
    }
    with use_models(ScriptedChatModel(replies=[reply])):
        result = graph.run(payload, ctx)
    assert result["switched"] == 0 and result["looks"] == 1 and result["scene_looks"] == 1
    assert any("rebuild with the breakdown first" in t for t in ctx.ports.jobs.texts("warning"))


@pytest.mark.parametrize("finished", ["done", "failed"])
def test_a_finished_job_is_skipped(finished: str) -> None:
    ctx, payload, _ = _world()
    ctx.ports.jobs.status = finished
    assert graph.run(payload, ctx) == {"skipped": finished}
