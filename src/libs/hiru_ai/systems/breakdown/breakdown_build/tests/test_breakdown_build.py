"""The breakdown_build system on fakes (plan/2026-11-11 phases 2, 3, 5): Ekama through the whole creation with the lab's
saved model answers, today's columns filled from the memory, the packets kept, the stager before planning and the
one-scene refresh. No model, no network, no database."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from tests.breakdown import rehearsal
from tests.breakdown.test_breakdown_run import GOLD, Scripted

from contracts.breakdown import run as brun
from contracts.breakdown.schema import BlockW, EpisodeW, PresenceW, SceneBriefW, SpanW, StagerW
from contracts.jobs import DispatchPayload, JobKind
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.fakes import FakeBreakdown, FakeCanon, FakeDocs, FakeJobs, FakeMemory, FakeScenes, FakeStructure
from hiru_ai.core.llm import use_models
from hiru_ai.core.testing import ScriptedChatModel
from hiru_ai.systems.breakdown.breakdown_build import graph

PID = UUID("00000000-0000-0000-0000-0000000000aa")


def _world() -> tuple[RunContext, DispatchPayload]:
    production = {"id": str(PID), "settings": {}, "orientation": "horizontal"}
    docs = FakeDocs(
        [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "production_id": str(PID),
                "filename": "ekama.pdf",
                "confirmed_role": "script",
                "text_path": "t/ekama.txt",
            },
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "production_id": str(PID),
                "filename": "poster.pdf",
                "confirmed_role": "other",
                "text_path": "t/poster.txt",
            },
        ],
        {"t/ekama.txt": rehearsal.FIXTURE.read_text(encoding="utf-8"), "t/poster.txt": "x"},
    )
    ports = replace(
        Ports(),
        jobs=FakeJobs(),
        structure=FakeStructure(),
        canon=FakeCanon(),
        docs=docs,
        scenes=FakeScenes(production),
        memory=FakeMemory(),
        breakdown=FakeBreakdown(),
    )
    payload = DispatchPayload(job_id=uuid4(), kind=JobKind.STRUCTURE_BUILD, actor_user_id=uuid4(), production_id=PID)
    return RunContext(production_id=PID, ports=ports), payload


@pytest.fixture()
def built(monkeypatch):
    ctx, payload = _world()
    scripted = Scripted()
    monkeypatch.setattr(graph, "calls", lambda _ctx: scripted.calls())
    with use_models(ScriptedChatModel(replies=[])):  # a model is "there"; the scripted calls answer
        result = graph.run(payload, ctx)
    return ctx, payload, result, scripted


def test_creation_fills_today_s_columns_from_the_memory(built):
    ctx, _, result, scripted = built
    assert result["scenes"] == 9 and result["episodes"] == 1 and result["ready"] == 9, result
    assert len(scripted.asked["split"]) == 1  # the poster ('other') is not a story document
    structure = ctx.ports.structure
    assert len(structure.scene_rows) == 9
    s2 = next(r for r in structure.scene_rows if r["number"] == 2)
    lines = [ln for ln in structure.line_rows if ln["scene_id"] == s2["id"]]
    phone = [ln for ln in lines if ln["delivery"] == "on the phone"]
    assert len(phone) == 1 and phone[0]["text"].startswith("Route eka maru") and phone[0]["character_id"]
    names = {e["name"] for e in ctx.ports.canon.entity_rows}
    assert {"Dinu", "Aruni", "Nimal", "Mudalali"} <= names
    assert ctx.ports.memory.rows and all(r["source"] == "reader" for r in ctx.ports.memory.rows)
    stages = [e for e in ctx.ports.jobs.events if e["type"] == "stage" and e["state"] == "done"]
    assert [e["stage"] for e in stages] == ["read", "episodes", "scenes"]


def test_the_memories_and_packets_are_kept(built):
    ctx, _, _, _ = built
    store = ctx.ports.breakdown
    assert len(store.source_rows) == 1 and store.source_rows[0]["filename"] == "ekama.pdf"
    bd, sources, version = graph.load(ctx, PID)
    assert bd is not None and len(sources) == 1 and version == 1
    s2 = bd.scene("E01-S02")
    assert s2.row_id and len(s2.line_map) == len([b for b in s2.blocks if b["kind"] == "dialogue"])
    row = store.packet(s2.row_id)
    assert row["waits"] == [] and row["scene_key"] == "E01-S02" and row["packet"]["A_scene"]["id"] == "E01-S02"
    lines = {ln["id"] for ln in ctx.ports.structure.line_rows}
    assert set(s2.line_map.values()) <= lines  # Raphael's line ids are real rows


def test_a_second_build_keeps_the_same_rows(built, monkeypatch):
    ctx, payload, _, _ = built
    first = {(r["episode_id"], r["number"]): r["id"] for r in ctx.ports.structure.scene_rows}
    ctx.ports.jobs.status = "pending"
    monkeypatch.setattr(graph, "calls", lambda _ctx: Scripted().calls())
    with use_models(ScriptedChatModel(replies=[])):
        graph.run(payload.model_copy(update={"job_id": uuid4()}), ctx)
    again = {(r["episode_id"], r["number"]): r["id"] for r in ctx.ports.structure.scene_rows}
    assert first == again
    assert len(ctx.ports.breakdown.source_rows) == 1  # the source memory is written once


def test_no_model_fails_the_job_clearly():
    ctx, payload = _world()
    result = graph.run(payload, ctx)
    assert "AI model" in result["failed"] and ctx.ports.jobs.status == "failed"


def _scene_row(ctx: RunContext, key: str) -> dict:
    bd, _, _ = graph.load(ctx, PID)
    sc = bd.scene(key)
    row = next(r for r in ctx.ports.structure.scene_rows if r["id"] == sc.row_id)
    return {**row, "production_id": str(PID)}


def test_the_packet_waits_when_the_script_changed(built):
    ctx, _, _, _ = built
    row = _scene_row(ctx, "E01-S03")
    got, why = graph.packet_for(ctx, {**row, "script_version": int(row["script_version"]) + 1})
    assert got is None and "refresh" in why


def test_the_stager_runs_once_before_planning(built):
    ctx, _, _, _ = built
    row = _scene_row(ctx, "E01-S08")
    staged = StagerW.model_validate_json((GOLD / "stage_ekama_E01-S08.json").read_text(encoding="utf-8"))
    model = ScriptedChatModel(replies=[staged.model_dump()])
    with use_models(model):
        got, why = graph.packet_for(ctx, row)
    assert why == "" and got["stage"]["zones"] and len(model.calls) == 1
    assert ctx.ports.breakdown.staging[row["id"]]["by"] == "model"
    model = ScriptedChatModel(replies=[])
    with use_models(model):  # the second time: the stored map, no call
        again, _ = graph.packet_for(ctx, row)
    assert again["stage"] == got["stage"] and model.calls == []


def test_the_one_scene_refresh_follows_the_person_s_edit(built, monkeypatch):
    ctx, payload, _, _ = built
    row = _scene_row(ctx, "E01-S03")
    bd, _, _ = graph.load(ctx, PID)
    dinu = next(e.id for e in bd.entities if e.name == "Dinu")
    place = bd.scene("E01-S03").brief["place"]
    line_id = str(uuid4())
    edited = {
        **row,
        "script_version": int(row["script_version"]) + 1,
        "script": [
            {"kind": "action", "text": "Dinu waits by the door.", "line_id": None},
            {"kind": "dialogue", "text": "", "line_id": line_id},
        ],
    }
    ctx.ports.scenes.scene_rows = [edited]
    ctx.ports.scenes.line_rows = [{"id": line_id, "scene_id": row["id"], "ord": 0, "speaker": "Dinu", "text": "Hari."}]

    def episode(msg: str) -> EpisodeW:
        n = int(msg.split(": Dinu waits by the door.")[0].rsplit("\n", 1)[-1])
        return EpisodeW(
            scenes=[
                SceneBriefW(
                    scene="E01-S03",
                    title="The Wait",
                    summary="Dinu waits.",
                    purpose="A pause.",
                    place=place,
                    people=[PresenceW(person=dinu)],
                    blocks=[
                        BlockW(kind="action", spans=[SpanW(line=n, w_from=0, w_to=5)]),
                        BlockW(kind="dialogue", speaker=dinu, spans=[SpanW(line=n + 1, w_from=2, w_to=3)]),
                    ],
                )
            ]
        )

    monkeypatch.setattr(
        graph,
        "calls",
        lambda _ctx: brun.Calls(
            split=None,
            continuity=None,
            episode=episode,  # type: ignore[arg-type]
            repair=None,
        ),
    )  # type: ignore[arg-type]
    ctx.ports.jobs.status = "pending"
    with use_models(ScriptedChatModel(replies=[])):
        result = graph.run(
            payload.model_copy(update={"job_id": uuid4(), "state": {"breakdown_refresh": row["id"]}}), ctx
        )
    assert result.get("scene") == "E01-S03" and result["waits"] == [], result
    packet_row = ctx.ports.breakdown.packet(row["id"])
    assert packet_row["script_version"] == edited["script_version"]
    texts = [b["text"] for b in packet_row["packet"]["E_blocks"]]
    assert texts == ["Dinu waits by the door.", "Hari."]
    bd, _, _ = graph.load(ctx, PID)
    assert bd.scene("E01-S03").line_map == {"E01-S03-B02": line_id} and bd.version == 2
