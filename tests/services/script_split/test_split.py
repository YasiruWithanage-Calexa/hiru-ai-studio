from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from script_split.engine import pipeline, planner

from contracts.jobs import DispatchPayload, JobKind
from contracts.screenplay import parse_document
from contracts.shotplan import fit
from tests.services.doc_ingest.conftest import CORPUS
from tests.services.fakes import FakeJobs, FakeLLM

PID = uuid4()
EP = str(uuid4())
NIMAL, KAMALA = str(uuid4()), str(uuid4())


def scene_from_fixture(n: int = 0) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    doc = parse_document((CORPUS / "harbour-lights-ep01-script.fountain").read_text(encoding="utf-8"))
    parsed = doc.scenes[n]
    scene_id = str(uuid4())
    blocks, lines = [], []
    for b in parsed.blocks:
        if b.kind == "dialogue":
            lid = str(uuid4())
            lines.append({"id": lid, "production_id": str(PID), "scene_id": scene_id, "ord": len(lines),
                          "speaker": b.speaker.title(), "text": b.text, "delivery": b.delivery,
                          "character_id": {"NIMAL": NIMAL, "KAMALA": KAMALA}.get(b.speaker)})
            blocks.append({"kind": "dialogue", "text": "", "line_id": lid})
        else:
            blocks.append({"kind": b.kind, "text": b.text, "line_id": None})
    scene = {"id": scene_id, "production_id": str(PID), "episode_id": EP, "number": n + 1,
             "heading": parsed.heading.raw, "envelope_s": 60, "status": "draft", "script": blocks,
             "location_id": str(uuid4())}
    return scene, lines


class FakeStore:
    def __init__(self, scenes: list[tuple[dict[str, Any], list[dict[str, Any]]]],
                 settings: dict[str, Any] | None = None):
        self.scene_rows = {s["id"]: s for s, _ in scenes}
        self.line_rows = {s["id"]: ls for s, ls in scenes}
        self.settings = settings or {}
        self.shots: dict[str, list[dict[str, Any]]] = {}
        self.episode_status: dict[str, str] = {}

    def production(self, production_id: UUID) -> dict[str, Any] | None:
        return {"id": str(production_id), "orientation": "horizontal", "settings": self.settings}

    def scenes(self, production_id: UUID, scene_ids: list[str] | None) -> list[dict[str, Any]]:
        return [s for sid, s in self.scene_rows.items() if scene_ids is None or sid in scene_ids]

    def episodes(self, production_id: UUID) -> list[dict[str, Any]]:
        return [{"id": EP, "number": 1, "status": "building"}]

    def lines(self, scene_id: UUID) -> list[dict[str, Any]]:
        return self.line_rows[str(scene_id)]

    def characters(self, production_id: UUID) -> list[dict[str, Any]]:
        return [{"id": NIMAL, "code": "C02", "name": "Nimal"}, {"id": KAMALA, "code": "C01", "name": "Kamala"}]

    def scene_status(self, production_id: UUID) -> list[dict[str, Any]]:
        return [{"episode_id": s["episode_id"], "status": s["status"]} for s in self.scene_rows.values()]

    def replace_shots(self, scene_id: UUID, shots: list[dict[str, Any]], lines: list[dict[str, Any]],
                      scene_fields: dict[str, Any]) -> None:
        self.shots[str(scene_id)] = shots
        self.line_rows[str(scene_id)] = lines
        self.scene_rows[str(scene_id)].update(scene_fields)

    def set_episode_status(self, episode_id: str, status: str) -> None:
        self.episode_status[episode_id] = status


def payload(state: dict[str, Any] | None = None, pipeline_: list[JobKind] | None = None, cursor: int = 0):
    return DispatchPayload(job_id=uuid4(), kind=JobKind.SCRIPT_SPLIT, actor_user_id=uuid4(), production_id=PID,
                           pipeline=pipeline_ or [JobKind.SCRIPT_SPLIT], cursor=cursor, state=state or {})


def test_rules_plan_for_the_opening_scene():
    scene, lines = scene_from_fixture(0)
    items = pipeline.items_for(scene, lines)
    shots = planner.plan_by_rules(items)
    # establishing wide (long opening action) · Nimal's line · Kamala's reaction + line
    assert [(s.start, s.end, s.framing) for s in shots] == [(0, 1, "WIDE"), (1, 2, "MCU"), (2, 4, "MCU")]
    r = fit(items, shots, envelope_s=60)
    assert [s.duration_s for s in r.shots] == [6, 4, 4]  # 28 words of action → 6 s


def test_without_a_key_every_scene_is_split_by_rules_and_lines_are_bound():
    scenes = [scene_from_fixture(i) for i in range(6)]
    store, jobs = FakeStore(scenes), FakeJobs()
    result = pipeline.run(payload(), store, jobs, FakeLLM(enabled=False))
    assert result["scenes"] == 6 and result["shots"] == sum(len(v) for v in store.shots.values())
    assert jobs.status == "done"
    for scene_id, lines in store.line_rows.items():
        shot_ids = {s["id"] for s in store.shots[scene_id]}
        assert all(ln["shot_id"] in shot_ids for ln in lines)
    first = store.scene_rows[scenes[0][0]["id"]]
    assert first["status"] == "split" and first["fit_report"]["planner"] == "rules"
    assert store.episode_status == {EP: "ready"}


def test_line_text_is_never_changed():
    scene, lines = scene_from_fixture(3)
    before = [(ln["id"], ln["text"], ln["delivery"]) for ln in lines]
    store = FakeStore([(scene, lines)])
    pipeline.run(payload(), store, FakeJobs(), FakeLLM(enabled=False))
    after = [(ln["id"], ln["text"], ln["delivery"]) for ln in store.line_rows[scene["id"]]]
    assert after == before


def test_approved_scenes_are_left_alone():
    scene, lines = scene_from_fixture(0)
    scene["status"] = "approved"
    store = FakeStore([(scene, lines)])
    result = pipeline.run(payload(), store, FakeJobs(), FakeLLM(enabled=False))
    assert result["skipped"] == 1 and store.shots == {}


def test_fixed_eight_second_production():
    store = FakeStore([scene_from_fixture(0)], settings={"fixed_shot_seconds": 8})
    pipeline.run(payload(), store, FakeJobs(), FakeLLM(enabled=False))
    assert {s["duration_s"] for v in store.shots.values() for s in v} == {8}


def model_plan(system: str, user: str) -> dict[str, Any]:
    return {"shots": [
        {"start": 0, "end": 2, "framing": "WIDE", "title": "Nimal at the door", "sound_mode": "dialogue",
         "duration": 8, "camera_link": "cut"},
        {"start": 2, "end": 4, "framing": "CU", "title": "Kamala keeps cooking", "sound_mode": "dialogue",
         "duration": 6, "camera_link": "cut"}]}


def test_model_plan_is_used_and_fitted_and_the_critic_can_pass_it():
    store = FakeStore([scene_from_fixture(0)])
    llm = FakeLLM({"shot_plan": model_plan, "shot_review": lambda s, u: {"acceptable": True, "notes": []}})
    pipeline.run(payload(), store, FakeJobs(), llm)
    shots = next(iter(store.shots.values()))
    assert [(s["framing"], s["title"]) for s in shots] == [
        ("WIDE", "Nimal at the door"), ("CU", "Kamala keeps cooking")]
    assert [c["schema"] for c in llm.calls] == ["shot_plan", "shot_review"]
    assert llm.calls[0]["tier"] == "high" and "<script>" in llm.calls[0]["user"]
    assert next(iter(store.scene_rows.values()))["fit_report"]["planner"] == "model"


def test_critic_notes_drive_one_replan():
    store = FakeStore([scene_from_fixture(0)])
    llm = FakeLLM({"shot_plan": model_plan,
                   "shot_review": lambda s, u: {"acceptable": False, "notes": ["S02 needs Kamala's reaction"]}})
    pipeline.run(payload(), store, FakeJobs(), llm)
    assert [c["schema"] for c in llm.calls] == ["shot_plan", "shot_review", "shot_plan"]
    assert "S02 needs Kamala's reaction" in llm.calls[2]["user"]
    assert next(iter(store.scene_rows.values()))["fit_report"]["critic_notes"] == ["S02 needs Kamala's reaction"]


def test_model_failure_falls_back_to_rules():
    store = FakeStore([scene_from_fixture(0)])
    pipeline.run(payload(), store, FakeJobs(), FakeLLM({}))
    assert next(iter(store.scene_rows.values()))["fit_report"]["planner"] == "rules"


def test_a_build_hop_reports_continuity_and_finishes_the_job():
    scene, lines = scene_from_fixture(2)  # Mrs. Perera is not linked to a character here
    scene["location_id"] = None
    store, jobs = FakeStore([(scene, lines)]), FakeJobs(cursor=2)
    p = payload({"build": True, "scene_ids": [scene["id"]]},
                [JobKind.CANON_EXTRACT, JobKind.STRUCTURE_BUILD, JobKind.SCRIPT_SPLIT], cursor=2)
    pipeline.run(p, store, jobs, FakeLLM(enabled=False))
    warnings = jobs.texts("warning")
    assert any("no location" in w for w in warnings) and any("Mrs. Perera" in w for w in warnings)
    assert ("continuity", "done") in jobs.stages() and ("review", "active") in jobs.stages()
    assert jobs.status == "done"


def test_finished_and_stale_deliveries_are_skipped():
    store = FakeStore([scene_from_fixture(0)])
    assert pipeline.run(payload(), store, FakeJobs(status="done"), FakeLLM(enabled=False)) == {"skipped": "done"}
    assert pipeline.run(payload(), store, FakeJobs(cursor=1), FakeLLM(enabled=False)) == {"skipped": "stale hop"}
    assert store.shots == {}


def test_past_the_time_budget_the_rest_goes_to_another_delivery(monkeypatch):
    monkeypatch.setattr(pipeline, "TIME_BUDGET_S", -1.0)  # every wave after the first is "too late"
    scenes = [scene_from_fixture(i) for i in range(3)]
    store, jobs = FakeStore(scenes), FakeJobs()
    first = pipeline.run(payload({"build": True}), store, jobs, FakeLLM(enabled=False))
    assert first["scenes"] == 1 and first["continued"] == 2
    handoff = jobs.advanced[0]
    assert handoff["again"] is True and handoff["state"]["build"] is True
    left = handoff["state"]["scene_ids"]
    assert left == [scenes[1][0]["id"], scenes[2][0]["id"]]
    assert jobs.status == "running" and ("shots", "done") not in jobs.stages()

    monkeypatch.setattr(pipeline, "TIME_BUDGET_S", 1e9)
    again = FakeJobs()
    final = pipeline.run(payload(handoff["state"]), store, again, FakeLLM(enabled=False))
    assert final["scenes"] == 3 and again.status == "done"
    assert ("shots", "active") not in again.stages() and ("shots", "done") in again.stages()
    assert len(store.shots) == 3
