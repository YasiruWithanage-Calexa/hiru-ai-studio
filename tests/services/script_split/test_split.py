from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from script_split.engine import critic, pipeline, planner

from contracts.jobs import DispatchPayload, JobKind
from contracts.screenplay import parse_document
from contracts.shotplan import Item, ProposedShot, fit
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

    def neighbours(self, production_id: UUID) -> list[dict[str, Any]]:
        return [{k: s.get(k) for k in ("id", "episode_id", "number", "heading", "title")}
                for s in self.scene_rows.values()]

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
    # 28 words of action → 6 s; Kamala's reaction plays 1.5 s before her line, so that shot needs 6 s too
    assert [s.duration_s for s in r.shots] == [6, 4, 6]


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


def plan_calls(llm: Any) -> list[dict[str, Any]]:
    """The model calls that plan and review (the beat and scene readings before them have their own tests)."""
    return [c for c in llm.calls if c["schema"] not in ("beat_screen", "scene_reading")]


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
    assert [c["schema"] for c in plan_calls(llm)] == ["shot_plan", "shot_review"]
    assert plan_calls(llm)[0]["tier"] == "high" and "<script>" in plan_calls(llm)[0]["user"]
    assert next(iter(store.scene_rows.values()))["fit_report"]["planner"] == "model"


def test_critic_notes_drive_one_replan():
    store = FakeStore([scene_from_fixture(0)])
    llm = FakeLLM({"shot_plan": model_plan,
                   "shot_review": lambda s, u: {"acceptable": False, "notes": ["S02 needs Kamala's reaction"]}})
    pipeline.run(payload(), store, FakeJobs(), llm)
    assert [c["schema"] for c in plan_calls(llm)] == ["shot_plan", "shot_review", "shot_plan"]
    assert "S02 needs Kamala's reaction" in plan_calls(llm)[2]["user"]
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


# ── scoring plans on speech coverage ────────────────────────────────────────────────────────

def say(i: int, who: str, sid: str, words: int = 8) -> Item:
    return Item(i, "dialogue", " ".join(["word"] * words), who, sid, "", f"l{i}")


def act(i: int, words: int = 5) -> Item:
    return Item(i, "action", " ".join(["act"] * words))


def shots(*ranges: tuple[int, int]) -> list[dict[str, Any]]:
    return [{"start": a, "end": b, "framing": "MCU", "title": f"shot {n}", "sound_mode": "dialogue",
             "duration": 4, "camera_link": "cut"} for n, (a, b) in enumerate(ranges, start=1)]


def two_rounds(first: list[dict[str, Any]], revised: list[dict[str, Any]]) -> FakeLLM:
    """A model that plans `first`, is told to change it, and then plans `revised`."""
    def plan(system: str, user: str) -> dict[str, Any]:
        return {"shots": revised if "reviewer found" in user else first}
    return FakeLLM({"shot_plan": plan,
                    "shot_review": lambda s, u: {"acceptable": False, "notes": ["add a CU on Kamala"]}})


def plan_scene(items: list[Item], llm: FakeLLM, envelope_s: int):
    return pipeline.plan_scene(items, heading="INT. KITCHEN - DAY", envelope_s=envelope_s, fixed=None, llm=llm,
                               speaker_names={})


def test_a_revised_plan_that_runs_over_the_envelope_loses_to_the_first_plan():
    items = [act(0), say(1, "NIMAL", "c1"), say(2, "KAMALA", "c2"), act(3)]
    llm = two_rounds(shots((0, 2), (2, 4)), shots((0, 1), (1, 2), (2, 3), (3, 4)))  # the critic's extra shots
    result, used, notes = plan_scene(items, llm, envelope_s=12)
    assert used == "model" and notes == ["add a CU on Kamala"]
    assert [s.title for s in result.shots] == ["shot 1", "shot 2"] and result.total_s == 12


def test_a_full_tie_keeps_the_first_plan():
    items = [act(0), say(1, "NIMAL", "c1"), say(2, "KAMALA", "c2"), act(3)]
    first = shots((0, 2), (2, 4))
    revised = [{**s, "title": "reworded"} for s in first]
    result, _, _ = plan_scene(items, two_rounds(first, revised), envelope_s=12)
    assert [s.title for s in result.shots] == ["shot 1", "shot 2"]


def test_a_plan_with_a_two_speaker_shot_loses_to_one_without():
    items = [say(0, "NIMAL", "c1", 6), say(1, "KAMALA", "c2", 6), act(2, 3)]
    llm = two_rounds(shots((0, 2), (2, 3)), shots((0, 1), (1, 3)))
    result, _, _ = plan_scene(items, llm, envelope_s=60)
    assert [(s.start, s.end) for s in result.shots] == [(0, 1), (1, 3)]
    assert not [i for i in result.issues if i.code == "multi_speaker"]


def test_score_order_clipped_line_then_two_speakers_then_envelope_then_silence():
    items = [say(0, "NIMAL", "c1", 6), say(1, "KAMALA", "c2", 6), act(2, 40)]
    one_shot = fit(items, [ProposedShot(0, 2), ProposedShot(2, 3)], envelope_s=60)  # two speakers, 8 s silent
    apart = fit(items, [ProposedShot(0, 1), ProposedShot(1, 2), ProposedShot(2, 3)], envelope_s=60)
    assert critic.kernel_score(one_shot)[1] == 1 and critic.kernel_score(apart)[1] == 0
    assert critic.kernel_score(apart) < critic.kernel_score(one_shot)  # even though it runs longer
    clipped = fit([say(0, "NIMAL", "c1", 12)], [ProposedShot(0, 1, duration=4, duration_locked=True)],
                  envelope_s=60)
    assert critic.kernel_score(clipped)[0] > critic.kernel_score(one_shot)[0]


def test_silence_over_the_ceiling_is_a_problem_unless_the_scene_has_no_lines():
    mostly_silent = fit([act(0, 40), say(1, "NIMAL", "c1", 6)], [ProposedShot(0, 1), ProposedShot(1, 2)],
                        envelope_s=60)  # 8 s of 12 s silent
    assert mostly_silent.silent_share > critic.SILENT_SHARE_MAX and critic.issue_count(mostly_silent) == 1
    balanced = fit([act(0, 3), say(1, "NIMAL", "c1", 6), say(2, "KAMALA", "c2", 6)],
                   [ProposedShot(0, 2), ProposedShot(2, 3)], envelope_s=60)
    assert critic.issue_count(balanced) == 0
    only_action = fit([act(0, 40), act(1, 40)], [ProposedShot(0, 1), ProposedShot(1, 2)], envelope_s=60)
    assert only_action.silent_share == 1.0 and critic.issue_count(only_action) == 0


def test_the_critic_reads_the_envelope_and_an_extra_shot_it_asks_for_is_rejected():
    items = [act(0), say(1, "NIMAL", "c1"), say(2, "KAMALA", "c2"), act(3)]
    llm = two_rounds(shots((0, 2), (2, 4)), shots((0, 1), (1, 2), (2, 3), (3, 4)))
    result, _, _ = plan_scene(items, llm, envelope_s=12)
    review = next(c for c in llm.calls if c["schema"] == "shot_review")
    assert "Shot list:\nEnvelope: 12 s. Plan runs 12 s. Silent: 0 s." in review["user"]
    assert "Timing is checked by code" not in review["system"] and "do not ask for another shot" in review["system"]
    assert [c["schema"] for c in plan_calls(llm)] == ["shot_plan", "shot_review", "shot_plan"]  # re-planned once
    assert result.total_s == 12  # and the over-envelope re-plan was dropped by the score


def phone_call_scene() -> list[Item]:
    spoken = lambda i, who, text, delivery="": Item(i, "dialogue", text, who, who.lower(), delivery, f"l{i}")  # noqa: E731
    return [Item(0, "action", "Kasun hands the phone back."),
            spoken(1, "Kasun", "Started with five thousand."),
            spoken(2, "Anudi", "You made all this yourself?"),
            spoken(3, "Anudi's Father", "Anudi, where are you? Come home.", "on the phone"),
            spoken(4, "Anudi", "Maybe… I'll see you again.")]


def test_the_rules_plan_puts_a_phone_voice_in_a_voiceover_shot_framed_on_the_listener():
    items = phone_call_scene()
    proposal = planner.plan_by_rules(items)
    call = next(p for p in proposal if p.start <= 3 < p.end)
    assert (call.start, call.end, call.framing, call.sound_mode) == (3, 4, "MCU", "voiceover")
    assert call.title == "Anudi listens"
    r = fit(items, proposal, envelope_s=60)
    assert r.shots[[s.start for s in r.shots].index(3)].sound_mode.value == "voiceover"
    assert not [i for i in r.issues if i.code == "multi_speaker"]


def test_a_voice_off_screen_at_the_start_is_framed_on_the_next_person_on_camera():
    items = [Item(0, "dialogue", "Open the door!", "Nimal", "c1", "off screen", "l0"),
             Item(1, "dialogue", "Coming!", "Kamala", "c2", "", "l1")]
    first = planner.plan_by_rules(items)[0]
    assert (first.sound_mode, first.title) == ("voiceover", "Kamala listens")


# ── reporting ───────────────────────────────────────────────────────────────────────────────

def test_the_fit_report_names_silence_two_speaker_shots_and_voiceover_shots():
    items = phone_call_scene()
    result = fit(items, [ProposedShot(0, 1), ProposedShot(1, 3), ProposedShot(3, 4), ProposedShot(4, 5)],
                 envelope_s=60)
    report = pipeline.report(result, "rules", [])
    assert report["silent_s"] == 4 and report["silent_share"] == round(4 / result.total_s, 2)
    assert report["multi_speaker"] == [2]  # Kasun and Anudi share shot 2
    assert report["voiceover"] == [3]  # the father on the phone
    assert report["issues"][0].keys() == {"code", "message", "shot", "line_id"}


def test_the_build_says_per_episode_how_much_is_spoken_and_how_much_is_off_screen():
    scenes = [scene_from_fixture(i) for i in range(2)]
    scenes[0][1][0]["delivery"] = "on the phone"  # the first line of the first scene is heard, not seen
    store, jobs = FakeStore(scenes), FakeJobs()
    pipeline.run(payload({"build": True}), store, jobs, FakeLLM(enabled=False))
    [step] = jobs.texts("agent_step")
    results = [fit(pipeline.items_for(s, ls), planner.plan_by_rules(pipeline.items_for(s, ls)), envelope_s=60)
               for s, ls in scenes]
    total, silent = sum(r.total_s for r in results), sum(r.silent_s for r in results)
    over = f" ({total - 120} s over)" if total > 120 else ""
    assert step == f"Episode 1: {total} s{over}, {total - silent} s spoken, 1 line off screen"
    assert store.scene_rows[scenes[0][0]["id"]]["fit_report"]["voiceover"]


def test_episode_totals_survive_a_continued_delivery():
    scenes = [scene_from_fixture(i) for i in range(3)]
    one = FakeJobs()
    pipeline.run(payload({"build": True}), FakeStore(scenes), one, FakeLLM(enabled=False))
    store = FakeStore(scenes)
    import script_split.engine.pipeline as module
    original = module.TIME_BUDGET_S
    module.TIME_BUDGET_S = -1.0
    try:
        first_jobs = FakeJobs()
        pipeline.run(payload({"build": True}), store, first_jobs, FakeLLM(enabled=False))
        handoff = first_jobs.advanced[0]
        assert not first_jobs.texts("agent_step")  # said once, when the hop is complete
        module.TIME_BUDGET_S = 1e9
        last = FakeJobs()
        pipeline.run(payload(handoff["state"]), store, last, FakeLLM(enabled=False))
    finally:
        module.TIME_BUDGET_S = original
    assert last.texts("agent_step") == one.texts("agent_step") and len(one.texts("agent_step")) == 1
