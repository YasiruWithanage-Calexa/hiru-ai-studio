"""The shot_prompt step (plan/2026-11-20d phase 3): the lab's five answers against the product's checks, one good/bad
pair per check, the brief, the frame part and the stored record."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from hiru_ai.steps.shot_prompt import logic, step

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "see_ai_in_action.json").read_text(encoding="utf-8"))
CLOCK_SLIPS = {"2B-1": "three-quarters of a second", "2H-1": "four-second", "2I-1": "two seconds",
               "2D-1": "two seconds"}


def case(slate: str = "2B-1") -> tuple[dict, dict]:
    d = FIXTURE[slate]
    return copy.deepcopy(d["answer"]), copy.deepcopy(d["facts"])


@pytest.mark.parametrize("slate", sorted(FIXTURE))
def test_the_labs_five_answers_pass_every_lab_check_and_the_new_clock_check_finds_the_slips_the_lab_saw(slate):
    answer, facts = case(slate)
    faults = logic.check(answer, facts)
    if slate in CLOCK_SLIPS:  # lab finding 5: "three-quarters of a second into the shot"; D6 makes it a fault
        assert faults == [f"video: a clock or edit word ('{CLOCK_SLIPS[slate]}'); say what happens and in what order"]
    else:
        assert faults == []


def faults_of(answer: dict, facts: dict, mode: str = "both") -> list[str]:
    return step.run({"op": "check", "answer": answer, "facts": facts, "mode": mode})["faults"]


def test_good_2a1_is_clean():
    answer, facts = case("2A-1")
    assert faults_of(answer, facts) == []


def test_the_opening_must_hold_exactly_the_people_in_frame():
    answer, facts = case("2A-1")
    answer["opening"]["people"] = answer["opening"]["people"][:1]
    assert any(f.startswith("opening: people") for f in faults_of(answer, facts))


def test_every_person_is_named_in_the_frame_and_the_video_on_the_same_side():
    answer, facts = case("2B-1")
    answer["video"]["people"] = answer["video"]["people"].replace("frame left", "frame right")
    assert any("is on the right here but on the left in the opening" in f for f in faults_of(answer, facts))
    answer, facts = case("2B-1")
    answer["video"]["people"] = "She stands by the desk."
    assert any(f.startswith("video:") and "not named here" in f for f in faults_of(answer, facts))


def test_the_designs_angle_must_be_in_the_composition_in_physical_words():
    answer, facts = case("2B-1")  # slightly low, chest height
    answer["frame"]["composition"] = "A waist-up frame of the manager on the left third, looking space to the right."
    assert any("the design's angle is slightly low (chest)" in f for f in faults_of(answer, facts))


def test_the_planners_opening_size_must_be_said():
    answer, facts = case("2A-1")
    facts["camera"]["size"] = "WIDE"
    answer["frame"]["composition"] = "The camera sits at eye height on the two managers by the desk."
    assert any("the shot opens WIDE" in f for f in faults_of(answer, facts))


def test_a_still_has_no_motion():
    answer, facts = case("2A-1")
    answer["frame"]["people"] += " She begins to turn toward him."
    assert any("a still has no motion ('begins to')" in f for f in faults_of(answer, facts))


def test_no_gear_no_sinhala_no_line_ids_no_quotes():
    answer, facts = case("2A-1")
    answer["frame"]["composition"] += " The camera rests on a tripod."
    assert any("names camera gear ('tripod')" in f for f in faults_of(answer, facts))
    answer, facts = case("2A-1")
    answer["video"]["situation"] += " He answers L2."
    assert any("a line id" in f for f in faults_of(answer, facts))
    answer, facts = case("2A-1")
    answer["video"]["sound"] += " “Welcome”"
    assert any("quotation marks" in f for f in faults_of(answer, facts))


def test_every_line_once_in_order():
    answer, facts = case("2B-1")
    answer["video"]["flow"] = [s for s in answer["video"]["flow"] if s["kind"] != "line"]
    assert any(f.startswith("video: lines none, the clip speaks ['L2']") for f in faults_of(answer, facts))


def test_nobody_speaks_in_a_silent_clip_but_saying_so_is_allowed():
    answer, facts = case("2I-1")
    answer["video"]["flow"][0]["text"] = "Nobody speaks. He nods."
    assert not any("somebody speaks" in f for f in faults_of(answer, facts))
    answer["video"]["flow"][0]["text"] = "He says he agrees."
    assert any("somebody speaks" in f for f in faults_of(answer, facts))


def test_clock_and_edit_words_are_faults_but_a_door_handle_is_not():
    answer, facts = case("2A-1")
    answer["video"]["flow"][0]["text"] = "She grips the door handle and looks up."
    assert faults_of(answer, facts) == []
    answer["video"]["flow"][0]["text"] = "In the six-second shot she looks up before the cut."
    assert any("a clock or edit word" in f for f in faults_of(answer, facts))


def test_safe_depiction_and_notes_to_us():
    answer, facts = case("2A-1")
    answer["frame"]["background"] += " No blood anywhere."
    assert any("decline: blood" in f for f in faults_of(answer, facts))
    answer, facts = case("2A-1")
    answer["video"]["situation"] += " As the planner wants."
    assert any("a note to us" in f for f in faults_of(answer, facts))


def test_video_only_mode_checks_the_video_and_code_puts_the_stored_frame_back():
    answer, facts = case("2B-1")
    stored = {"opening": answer["opening"], "frame": answer["frame"]}
    changed = copy.deepcopy(answer)
    changed["frame"]["composition"] = "Something else entirely, moving."
    fixed = step.run({"op": "fixed", "answer": changed, "stored": stored})["answer"]
    assert fixed["frame"] == answer["frame"]
    changed["frame"]["composition"] = "A flat view."  # the frame is not the agent's to change in video-only mode
    assert not any(f.startswith("frame: the design") for f in faults_of(changed, facts, mode="video_only"))


def test_a_shot_with_nobody_in_frame_has_nobody_in_its_opening():
    answer, facts = case("2D-1")
    assert facts["in_frame"] == [] and answer["opening"]["people"] == []
    answer["opening"]["people"] = [{"name": "Visitor", "side": "left", "facing": "screen", "posture": "", "hands": "",
                                   "expression": ""}]
    assert any(f.startswith("opening: people") for f in faults_of(answer, facts))


def test_the_brief_states_the_facts_the_camera_and_never_a_lines_words_as_its_own():
    _, facts = case("2B-1")
    out = step.run({"op": "brief", "facts": facts})
    assert out["shot"].startswith('<shot slate="2B-1">') and "- L2: Company B Operations Manager" in out["shot"]
    assert "Planner's opening picture: Waist-up" in out["shot"]
    assert "Productivity" not in out["shot"]  # the words are never in the shot brief: code puts them in
    assert out["camera"].startswith("<camera> (the Camera agent's design: keep it)")
    assert "Angle slightly low, height chest height." in out["camera"]
    assert "The video's camera line (code puts it in): From a slightly low" in out["camera"]
    assert out["cards"] == ["dialogue", "sinhala_voice"]
    _, silent = case("2D-1")
    assert "Nobody is in frame." in step.run({"op": "brief", "facts": silent})["shot"]


def test_camera_facts_from_the_panel_and_the_design():
    c = step.run({"op": "camera", "settings": {"angle": "Low angle", "height": "Hip height", "framing": "Medium shot",
                                               "movement": "Push in", "speed": "Slow", "lens": "35mm"},
                  "block": {"opens_on": "waist-up", "trigger": "L4"}, "sentence": "The camera moves in."})["camera"]
    assert (c["angle"], c["height"], c["size"], c["designed"], c["trigger"]) == ("low", "hip", "MS", True, "L4")
    assert step.run({"op": "camera", "settings": {}, "block": None, "sentence": ""})["camera"]["designed"] is False


def test_the_record_and_the_frame_part():
    answer, _ = case("2B-1")
    rec = step.run({"op": "record", "answer": answer, "model": "gpt-6.1-sol", "job_id": "j1",
                    "pins": {"shot_version": 1}, "repaired": True})["record"]
    assert set(rec) >= {"opening", "frame", "video", "pins", "model", "job_id", "written_at"} and rec["repaired"]
    frame = step.run({"op": "frame", "record": rec})["frame"]
    assert frame["composition"].startswith("The camera sits low") and set(frame) == {"composition", "people",
                                                                                    "background", "light"}
    assert step.run({"op": "frame", "record": None})["frame"]["composition"] == ""
    direction = step.run({"op": "direction", "answer": answer})["direction"]
    assert set(direction) == {"situation", "people", "flow", "sound"}


# ── timecodes (lab/timecodes, 2026-11-21) ─────────────────────────────────────────────────────────────────────────


def _times(answer: dict, *ranges: tuple[float, float]) -> dict:
    for s, (a, b) in zip(answer["video"]["flow"], ranges, strict=True):
        s["start_s"], s["end_s"] = a, b
    return answer


@pytest.mark.parametrize(("ranges", "says"), [
    (((0.5, 1), (1, 5), (5, 6)), "must run from 0 to 6 s"),
    (((0, 1), (1, 5), (5, 5.5)), "must run from 0 to 6 s"),
    (((0, 1), (1.5, 5), (5, 6)), "step 1 ends at 1 s but step 2 starts at 1.5 s"),
    (((0, 0.5), (0.5, 5), (5, 6)), "step 1 lasts 0.5 s"),
    (((0, 1.25), (1.25, 5), (5, 6)), "whole or half seconds only"),
    (((0, 3), (3, 5), (5, 6)), "s of words in 2 s"),
])
def test_each_timing_check_refuses_its_fault_and_the_labs_ranges_pass(ranges, says):
    answer, facts = case("2B-1")  # 6 s, one line of about 4.5 s; the lab's ranges 0-1, 1-5, 5-6
    clean = [f for f in faults_of(answer, facts) if "clock or edit word" not in f]
    assert clean == []
    bad = [f for f in faults_of(_times(answer, *ranges), facts) if "clock or edit word" not in f]
    assert any(says in f for f in bad), bad


def test_a_step_with_no_time_and_too_many_steps_are_faults():
    answer, facts = case("2H-1")  # 4 s
    del answer["video"]["flow"][0]["start_s"]
    assert "video: every step needs its start_s and end_s" in faults_of(answer, facts)
    answer, facts = case("2H-1")
    flow = answer["video"]["flow"]
    answer["video"]["flow"] = [dict(flow[0]), dict(flow[0]), dict(flow[1]), dict(flow[1])]
    _times(answer, (0, 1), (1, 2), (2, 3), (3, 4))
    assert any("4 steps in 4 s" in f for f in faults_of(answer, facts))
