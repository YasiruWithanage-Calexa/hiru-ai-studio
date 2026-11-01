"""Pictures in the split (plan/2026-11-01b Phases 2-4, 6): the beat reading, implied steps, a planner and
a critic that see time."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from script_split.engine import beats, critic, pipeline, planner

from contracts import bridges
from contracts.beats import Reading
from contracts.shotplan import Item, ProposedShot, fit
from tests.services import scene2_fixture as scene2
from tests.services.fakes import FakeJobs, FakeLLM
from tests.services.script_split.test_split import FakeStore, payload

ENV = 35


def scene2_scene(**extra: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scene = {**scene2.scene_row(), "production_id": str(uuid4()), "episode_id": "ep", "script": scene2.blocks(),
             "script_version": 3, "status": "draft", "location_id": str(uuid4()), **extra}
    return scene, scene2.lines()


def raising(*_: Any) -> dict[str, Any]:
    raise RuntimeError("down")


# ── Phase 2: the reading ──────────────────────────────────────────────────────────────────


def test_a_model_answer_is_validated_block_by_block_and_the_rules_fill_the_gaps():
    items = scene2.items(screens=False)
    answer = {"blocks": [{"block": 18, "screen": "inner", "events": 1},
                         {"block": 10, "screen": "act", "events": 9},  # events are clamped
                         {"block": 11, "screen": "hovering", "events": 1},  # not a screen kind: dropped
                         {"block": 2, "screen": "act", "events": 1},  # a dialogue block: dropped
                         {"block": 99, "screen": "act", "events": 1},  # no such block: dropped
                         {"block": "x"}]}  # malformed: dropped
    readings, by = beats.classify(lambda s, u: answer, items)
    assert by == "model"
    assert readings[18] == Reading("inner", 1) and readings[10] == Reading("act", 6)
    assert readings[11].screen == "info" and readings[1].screen == "move"  # the rules read what it left out
    assert 2 not in readings and 99 not in readings


def test_without_a_key_or_when_the_call_fails_the_rules_read_every_action_block():
    items = scene2.items(screens=False)
    every = {i.index for i in items if i.kind == "action"}
    for ask in (None, raising, lambda s, u: {"blocks": []}):
        readings, by = beats.classify(ask, items)
        assert by == "rules" and set(readings) == every


def test_the_split_reads_each_scene_once_per_script_version_on_the_medium_tier():
    scene, lines = scene2_scene()
    store = FakeStore([(scene, lines)])
    llm = FakeLLM({"beat_screen": lambda s, u: {"blocks": [{"block": 18, "screen": "inner", "events": 1}]}})
    pipeline.run(payload(), store, FakeJobs(), llm)
    reads = [c for c in llm.calls if c["schema"] == "beat_screen"]
    assert len(reads) == 1 and reads[0]["tier"] == "medium" and "<script>" in reads[0]["user"]
    script = store.scene_rows[scene["id"]]["script"]
    assert all(b["for_version"] == 3 and b["by"] in ("model", "rules") for b in script if b["kind"] == "action")
    assert [b["text"] for b in script if b["kind"] == "action" and not b.get("implied")] == [
        b["text"] for b in scene2.blocks() if b["kind"] == "action"]  # not one block was rewritten
    # a second split of the same version does not read again
    store.scene_rows[scene["id"]]["status"] = "draft"
    llm.calls.clear()
    pipeline.run(payload(), store, FakeJobs(), llm)
    assert not [c for c in llm.calls if c["schema"] == "beat_screen"]
    # a new script version does
    store.scene_rows[scene["id"]]["script_version"] = 4
    store.scene_rows[scene["id"]]["status"] = "draft"
    pipeline.run(payload(), store, FakeJobs(), llm)
    assert len([c for c in llm.calls if c["schema"] == "beat_screen"]) == 1


def test_without_a_key_the_rules_read_and_the_picture_clock_still_runs():
    scene, lines = scene2_scene()
    store = FakeStore([(scene, lines)])
    pipeline.run(payload(), store, FakeJobs(), FakeLLM(enabled=False))
    stored = store.scene_rows[scene["id"]]
    assert all(b["by"] == "rules" for b in stored["script"] if b["kind"] == "action")
    assert stored["fit_report"]["need_s"] > 0 and stored["fit_report"]["planner"] == "rules"


# ── Phase 3: implied steps ────────────────────────────────────────────────────────────────


def test_the_split_adds_the_answer_and_a_removed_one_never_comes_back():
    scene, lines = scene2_scene()
    store = FakeStore([(scene, lines)])
    pipeline.run(payload(), store, FakeJobs(), FakeLLM(enabled=False))
    script = store.scene_rows[scene["id"]]["script"]
    answers = [i for i, b in enumerate(script) if b.get("bridge") == bridges.ANSWER_PHONE]
    assert len(answers) == 1 and script[answers[0]]["text"] == "Anudi answers the phone."
    shots = store.shots[scene["id"]]
    assert max(s["block_end"] for s in shots) == len(script)  # shots cover the script that includes it
    # the person removes it; a re-split respects that
    store.scene_rows[scene["id"]]["script"] = bridges.skip_bridge(script, answers[0])
    store.scene_rows[scene["id"]]["status"] = "draft"
    pipeline.run(payload(), store, FakeJobs(), FakeLLM(enabled=False))
    assert not [b for b in store.scene_rows[scene["id"]]["script"] if b.get("bridge") == bridges.ANSWER_PHONE]


def test_an_approved_scene_gets_no_new_steps():
    scene, lines = scene2_scene(status="approved")
    store = FakeStore([(scene, lines)])
    pipeline.run(payload(), store, FakeJobs(), FakeLLM(enabled=False))
    assert store.shots == {} and store.scene_rows[scene["id"]]["script"] == scene2.blocks()


# ── Phase 4: the planner and the critic see time ──────────────────────────────────────────


def test_the_listing_shows_kinds_and_seconds():
    text = planner.scene_listing(scene2.items(), {})
    assert "[10] ACTION (act, 1.5 s): Suddenly, her phone rang." in text
    assert "[11] INFO (needs a carrier): It is her father (voice only)." in text
    assert "[18] STORY NOTE (not filmed): He has no idea that this meeting is about to change his life." in text
    assert "[14] ACTION (with_line, 0.5 s): She looked at Kasun one more time." in text
    assert "[1] ACTION (move, 2.5 s)" in text and "DIALOGUE (" in text and "words, " in text


def test_the_static_planner_text_names_the_rules_and_does_not_depend_on_the_scene():
    assert "turn in feeling" in planner.PLAN_SYSTEM and "INFO block" in planner.PLAN_SYSTEM
    assert "STORY NOTE" in planner.PLAN_SYSTEM and "starts only after its source is shown" in planner.PLAN_SYSTEM
    assert "{" not in planner.PLAN_SYSTEM and "Envelope:" not in planner.PLAN_SYSTEM  # static: scene data goes last


def prepared() -> list[Item]:
    scene, lines = scene2_scene()
    return pipeline.prepare(scene, lines, FakeLLM(enabled=False))[1]


def test_the_rules_plan_for_scene_2_has_no_crowded_shot_and_the_voice_follows_the_ring():
    items = prepared()
    rules = fit(items, planner.plan_by_rules(items, envelope_s=ENV), envelope_s=ENV)
    assert not rules.crowded and not [i for i in rules.issues if i.code in ("split", "line_overrun")]
    ring = next(i.index for i in items if "rang" in i.text)
    voice = next(s for s in rules.shots if s.line_ids == ["l5"])
    assert voice.start > ring and voice.sound_mode.value == "voiceover"
    father = next(ln for ln in rules.lines if ln.line_id == "l5")
    assert father.start_s == voice.start_s + 0.5  # nothing but the voice in that shot
    answers = next(i.index for i in items if i.bridge == bridges.ANSWER_PHONE)
    assert any(s.start <= answers < s.end and s.end <= voice.start for s in rules.shots)


def test_a_model_plan_that_keeps_todays_s05_loses_to_the_rules_plan():
    items = prepared()
    call = next(i.index for i in items if i.line_id == "l5")
    start = next(i.index for i in items if i.text == "Anudi smiled back.")
    cuts = [(0, start), (start, call + 1), (call + 1, len(items))]

    def todays_plan(system: str, user: str) -> dict[str, Any]:
        return {"shots": [{"start": a, "end": b, "framing": "MCU", "title": f"shot {n}", "sound_mode": "dialogue",
                           "duration": 8, "camera_link": "cut"} for n, (a, b) in enumerate(cuts, start=1)]}

    llm = FakeLLM({"shot_plan": todays_plan, "shot_review": lambda s, u: {"acceptable": True, "notes": []}})
    result, used, _ = pipeline.plan_scene(items, heading="EXT.", envelope_s=ENV, fixed=None, llm=llm,
                                          speaker_names={})
    assert used == "rules"
    model = fit(items, [ProposedShot(a, b, "MCU", "x", None, 8) for a, b in cuts], envelope_s=ENV)
    assert critic.kernel_score(model) > critic.kernel_score(result)  # it held more than a shot can show
    assert any(i.code == "split" for i in model.issues)


def test_the_critic_describes_need_in_the_shot_and_a_crowded_line_replaces_busy():
    items = prepared()
    locked = fit(items, [ProposedShot(0, len(items), "MCU", "all of it", None, 4, True)], envelope_s=ENV)
    text = critic.describe(locked, items)
    assert "CROWDED: S01 (needs" in text and "BUSY" not in text
    assert "need " in text.splitlines()[-1] and " s in 4 s," in text
    assert "CROWDED line" in critic.CRITIC_SYSTEM
    assert locked.crowded == [1] and critic.issue_count(locked) >= 1


def test_folding_a_silent_shot_stops_before_it_crowds_the_neighbour():
    items = prepared()
    shots = planner.plan_by_rules(items, envelope_s=1)  # absurd: nothing may be squeezed to fit
    result = fit(items, shots, envelope_s=1)
    assert not result.crowded and result.need_s > result.envelope_s
    env = next(i for i in result.issues if i.code == "envelope")
    assert f"needs {result.need_s} s on screen; its envelope is 1 s" in env.message


# ── Phase 6: honest envelopes ─────────────────────────────────────────────────────────────


def test_the_build_line_says_what_the_script_needs():
    stats = {"total_s": 70, "envelope_s": 60, "silent_s": 10, "off_screen": 1, "need_s": 78}
    assert pipeline.episode_line(1, stats) == (
        "Episode 1: needs 78 s to show its script; target 60 s, 60 s spoken, 1 line off screen")
    roomy = {"total_s": 40, "envelope_s": 60, "silent_s": 10, "off_screen": 0, "need_s": 40}
    assert pipeline.episode_line(2, roomy) == "Episode 2: 40 s, 30 s spoken"


def test_the_scene_report_carries_need_and_crowded():
    scene, lines = scene2_scene()
    store = FakeStore([(scene, lines)])
    pipeline.run(payload(), store, FakeJobs(), FakeLLM(enabled=False))
    report = store.scene_rows[scene["id"]]["fit_report"]
    assert report["crowded"] == [] and report["need_s"] >= report["total_s"]
