"""Tests that live with the camera_design step (plan/2026-11-20c §4, phase 3; plan/2026-11-20d §6): the gates on
lab/camera_moves' scenes (`fixtures/camera_moves.json`: the chase, Ekama S03, Api Denna S04, with gpt-6.1-sol's
cinematic answers); the brief and the knowledge base on Api Denna E01-S04 as lab/camera_agent briefed it
(`fixtures/camera_e01_s04.json`)."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from contracts import camera as cam
from contracts.producer import CameraSettings, default_camera
from hiru_ai.steps.camera_design import brief, gates, kb, merge, step, words

DATA = json.loads((Path(__file__).parent / "fixtures" / "camera_e01_s04.json").read_text(encoding="utf-8"))
RUN4 = DATA["run4"]  # the clips as lab/camera_agent briefed them (the brief and kb tests read their shape)
MOVES = json.loads((Path(__file__).parent / "fixtures" / "camera_moves.json").read_text(encoding="utf-8"))
CHASE = MOVES["chase"]  # plan/2026-11-20d §6: lab/camera_moves' chase scene and gpt-6.1-sol's cinematic answer


def clip_of(run: dict[str, Any], slate: str) -> dict[str, Any]:
    return next(c for c in run["clips"] if c["slate"] == slate)


def subject_first(c: dict[str, Any]) -> dict[str, Any]:
    """The lab's sentences were written before §6.3 ("the camera" as the subject): the same sentence with it."""
    s = str(c.get("camera_sentence") or "")
    if c.get("move") not in cam.STILL_MOVES and "the camera" not in s.lower():
        c["camera_sentence"] = "The camera, " + s[:1].lower() + s[1:]
    return c


def answer_of(run: dict[str, Any], slate: str) -> dict[str, Any]:
    return subject_first(copy.deepcopy(next(c for c in run["answer"]["clips"] if c["slate"] == slate)))


def scene_answer(run: dict[str, Any]) -> dict[str, Any]:
    a = copy.deepcopy(run["answer"])
    a["clips"] = [subject_first(c) for c in a["clips"]]
    return a


def faults_of(c: dict[str, Any], clip: dict[str, Any]) -> list[str]:
    return gates.check_clip(c, clip)[0]


# ── the lab's answers pass ─────────────────────────────────────────────────────────────────────────────────────────


def test_the_chase_answer_passes_every_gate_once_the_camera_is_the_subject():
    """lab/camera_moves' chase: 20 clips, pursuit at 4, the box reveal at 5, a crane up to finish. Its sentences were
    imperative ("pan slowly right as..."); §6.3 asks for "the camera" as the subject, and that is all it is short of."""
    raw, _ = gates.check_scene(CHASE["answer"], CHASE["clips"])
    assert raw and all("\"the camera\" as its subject" in f for f in raw)
    assert gates.check_scene(scene_answer(CHASE), CHASE["clips"])[0] == []


def test_the_production_direction_softens_the_shares_and_ekama_s03_varies_too_little():
    """Ekama S03: 13 of 23 moves go forward (push_in, push_then_hold, slow_creep): the family rule (§6.4) asks for a
    repair the per-move rule never saw."""
    s03 = MOVES["ekama_s03"]
    faults, _ = gates.check_scene(scene_answer(s03), s03["clips"])
    assert faults == ["scene: the forward family on 13 of 23 clips; vary the ways the camera moves"]


# ── one good / bad pair per gate ─────────────────────────────────────────────────────────────────────────────────────

PUSH = "1B-2"  # push_in, MCU -> CU, slightly low, a speaking face (Rohan calls across the lane)


@pytest.mark.parametrize(("change", "says"), [
    ({"start_s": 2.0, "end_s": 9.0}, "outside a"),
    ({"speed": "none"}, "with speed none"),
    ({"trigger": ""}, "has no trigger"),
    ({"speed": "fast"}, "breaks lip-sync"),
    ({"move": "whip_pan"}, "breaks lip-sync"),
    ({"time": "slow_motion"}, "with a spoken line"),
    ({"end_size": "WIDE"}, "cannot land on"),
    ({"camera_sentence": "The camera pushes in on the dolly toward his face."}, "names gear"),
    ({"camera_sentence": "The camera slowly pushes in toward his face as he says L4."}, "line id"),
    ({"camera_sentence": "The camera slowly pushes in toward his face before the cut."}, "edit/clock word"),
    ({"camera_sentence": "The camera slowly pushes in " + "very " * 45 + "closely."}, "characters (max 220)"),
    ({"camera_sentence": "The camera barely pushes in toward his face."}, "reads as no movement"),
    ({"camera_sentence": "The camera slowly pushes in, keeping his lips clear."}, "picture rule"),
    ({"camera_sentence": "A static, locked-off medium shot, then the camera pushes in."}, "but the sentence says"),
    ({"camera_sentence": "A medium shot of his face as he calls."}, "has no move in it"),
    ({"camera_sentence": "Push slowly closer as he calls across the lane."}, "as its subject"),
    ({"focus": "rack_focus"}, "rack focus without"),
    ({"intensity": 0}, "is not 1-5"),
    ({"angle": "dutch", "intensity": 3}, "only at 4-5"),
    ({"angle_reason": ""}, "with no angle_reason"),
])
def test_each_clip_gate_refuses_its_fault_and_passes_the_labs_answer(change: dict[str, Any], says: str):
    clip = clip_of(CHASE, PUSH)
    good = answer_of(CHASE, PUSH)
    assert faults_of(good, clip) == []
    bad = {**good, **change}
    assert any(says in f for f in faults_of(bad, clip)), faults_of(bad, clip)


def test_a_long_move_needs_its_time_and_a_hold_has_no_move_words():
    clip = {**clip_of(CHASE, "1R-1"), "take_s": 8}
    orbit = {**answer_of(CHASE, "1R-1"), "move": "orbit", "speed": "slow", "start_s": 1, "end_s": 4, "omni": "risky",
             "camera_sentence": "The camera circles all the way around him as he kneels."}
    assert any("needs at least 8 s" in f for f in faults_of(orbit, clip))
    hold = {**answer_of(CHASE, "1Q-1"), "support": "locked_off",
            "camera_sentence": "The camera slowly pushes toward the wall."}
    assert any("locked-off hold, but the sentence" in f for f in faults_of(hold, clip_of(CHASE, "1Q-1")))


def test_scene_gates_holds_share_variety_by_family_and_order():
    clips = CHASE["clips"]
    a = scene_answer(CHASE)
    for c in a["clips"][:7]:  # seven holds of 20 (at most 5)
        c.update(move="hold", speed="none", start_s=0, end_s=0, trigger="", camera_sentence="The camera holds still.")
    assert any("holds or floats" in f for f in gates.check_scene(a, clips)[0])
    assert any("holds or floats" in n for n in gates.check_scene(a, clips, locked=True)[1])  # the production's own
    assert not any("holds or floats" in f for f in gates.check_scene(a, clips, locked=True)[0])
    a = scene_answer(CHASE)
    for i, c in enumerate(a["clips"][:10]):  # push_in / slow_creep / push_then_hold: one family (§6.4)
        if c["move"] not in cam.HOLDS:
            c["move"] = ("push_in", "slow_creep", "push_then_hold")[i % 3]
    assert any("forward family" in f for f in gates.check_scene(a, clips)[0])
    a = scene_answer(CHASE)
    a["clips"] = a["clips"][::-1]
    assert any("answer slates" in f for f in gates.check_scene(a, clips)[0])


def test_the_peak_gets_the_strongest_camera():
    clips = CHASE["clips"]
    a = scene_answer(CHASE)
    a["peak_slate"] = "1Z-9"
    assert any("is not a clip" in f for f in gates.check_scene(a, clips)[0])
    a = scene_answer(CHASE)
    a["peak_slate"] = "1A-1"  # intensity 2: another clip has 5
    assert any("another clip has 5" in f for f in gates.check_scene(a, clips)[0])
    a = scene_answer(CHASE)
    calm = next(c for c in a["clips"] if c["slate"] == "1T-1")  # intensity 2: a fast crash zoom outranks the peak
    calm.update(move="crash_zoom", speed="fast", intensity=2)
    faults = gates.check_scene(a, clips)[0]
    assert any("stronger camera than the peak" in f for f in faults) and any("only at 4-5" in f for f in faults)


def test_the_angle_gate_wants_a_share_off_eye_level_with_a_turn_and_is_quiet_below():
    clips = CHASE["clips"]
    a = scene_answer(CHASE)
    for c in a["clips"]:
        c.update(angle="eye_level", height="eye", angle_reason="")
    assert any("every clip is eye level" in f for f in gates.check_scene(a, clips)[0])
    for c in a["clips"][:5]:  # 15 of 20 still at eye level: more than two in three
        c.update(angle="slightly_low", angle_reason="low on his flight")
    assert any("at most two in three" in f for f in gates.check_scene(a, clips)[0])
    for c in a["clips"][5:8]:
        c.update(angle="high", angle_reason="small in the lane")
    assert not any("eye level" in f for f in gates.check_scene(a, clips)[0])
    small = {**a, "peak_slate": a["clips"][0]["slate"],
             "clips": [dict(c, angle="eye_level", height="eye") for c in a["clips"][:5]]}
    assert not any("eye level" in f for f in gates.check_scene(small, clips[:5])[0])


def test_a_one_shot_answer_is_checked_alone_and_its_scene_shares_are_advice():
    clips = copy.deepcopy(CHASE["clips"])
    for c in clips:  # the rest of the scene: rule holds (today's panel)
        c["current"] = {"move": "hold", "speed": "none", "angle": "eye_level", "height": "eye", "axis": "side_a"}
    one = {"camera_language": "x", "arc": "", "peak_slate": "", "clips": [answer_of(CHASE, PUSH)]}
    faults, notes = gates.check_scene(one, clips, focus=[PUSH])
    assert faults == [] and any("holds or floats" in n for n in notes)
    assert gates.check_scene(one, clips, focus=["1B-1"])[0]  # answered the wrong clip


def test_faulty_slates_names_only_clips():
    assert gates.faulty_slates(["4C-1: x", "scene: y", "4E-2: z"], ["4C-1", "4E-2", "4A-1"]) == {"4C-1", "4E-2"}


# ── the brief and the knowledge base ─────────────────────────────────────────────────────────────────────────────────


def test_the_menu_has_every_move_from_the_base_or_the_catalogue():
    text = kb.menu()
    assert text.startswith("<moves>") and text.endswith("</moves>")
    for m in cam.MOVES:
        assert f"- {m.slug}" in text
    assert "Use:" in text and "rack_focus:" in text


def test_fits_keeps_fast_moves_off_a_speaking_face_aerials_off_interiors_and_long_moves_out_of_short_takes():
    speaking = {"speaks": True, "take_s": 4, "role": "single", "exterior": True}
    assert "whip_pan" not in kb.fits(speaking) and "push_in" in kb.fits(speaking)
    assert "aerial_establishing" not in kb.fits(speaking)
    assert "aerial_establishing" in kb.fits({"speaks": False, "take_s": 8, "role": "master", "exterior": True})
    assert "orbit" not in kb.fits({"speaks": False, "take_s": 6, "role": "master", "exterior": False})


def test_ideas_map_search_rows_to_moves_that_fit():
    rows = [{"slug": "static_locked_off_shot", "effect": "stillness"},
            {"slug": "pan", "effect": "Follows or discovers", "use_case": "a look that finds something"},
            {"slug": "whip_pan", "effect": "energy"},
            {"slug": "dolly", "effect": "intimacy", "use_case": "a line lands"}]
    got = kb.ideas(rows, kb.fits({"speaks": True, "take_s": 4, "role": "single"}))
    assert [m for m, _ in got] == ["pan_left / pan_right / follow_pan / slow_pan_reveal", "push_in"]
    assert "use: a look that finds something" in got[0][1]


def test_the_brief_scene_part_is_the_same_bytes_and_carries_the_table():
    a = brief.scene_part("<scene>\nS04\n</scene>")
    assert a == brief.scene_part("<scene>\nS04\n</scene>") and "<moves>" in a and "<omni>" in a
    assert "MEASURED" in a and "half_orbit" in a


def test_the_clips_part_names_size_take_and_who_speaks():
    clip = {**clip_of(RUN4, "4E-2"), "spoken": [{"lid": "L11", "speaker": "Father", "heard": True, "seconds": 4.2}],
            "in_frame": [{"description": "Anudi", "position": "centre", "action": "listens"}], "heard": ["Father"],
            "cinematic": False, "technique": "locked_off"}
    text = brief.clips_part([clip], {"4E-2": [("push_in", "intimacy; use: a line lands")]})
    assert '<clip slate="4E-2" n="1">' in text and "SIZE CU" in text and "take 8.0 s" in text
    assert "L11 Father (heard, not seen) (~4.2 s)" in text and "Only heard, never seen: Father" in text
    assert "Ideas from the knowledge base" in text and "push_in: intimacy" in text


# ── the merge ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_merge_writes_the_panel_words_keeps_the_size_and_light_and_stores_the_block():
    base = default_camera("CU", heading="EXT. ROAD - DAY")
    c = answer_of(CHASE, "1K-2")
    design = merge.merged({"rationale": "the demand", "pins": {"x": 1}}, c, base=base, language="eases closer",
                          model="gpt-6.1-sol", job_id="j1", arc="2 to 5 at the box", peak="1M-1")
    rec = CameraSettings.model_validate(design["recommended"])
    assert rec.framing == base.framing and rec.lighting == base.lighting  # D4: the planner's size; no lighting
    assert rec.movement == "Push, then hold" and rec.speed == "Slow" and rec.lens == c["lens"]
    assert rec.angle == cam.label_of("angle", c["angle"]) and rec.height and rec.support
    block = design["camera"]
    assert block["state"] == "designed" and block["camera_sentence"] == c["camera_sentence"]
    assert block["language"] == "eases closer" and block["trigger"] == c["trigger"] and design["pins"] == {"x": 1}
    assert block["moment"] == c["moment"] and block["intensity"] == c["intensity"] and block["power"] == c["power"]
    assert block["angle_reason"] == c["angle_reason"] and block["arc"] == "2 to 5 at the box"
    assert block["peak_slate"] == "1M-1"
    now = merge.current_of(design)
    assert now["move"] == "push_then_hold" and now["moment"] == c["moment"] and merge.designed(design)


def test_merge_falls_back_to_the_rule_camera_with_the_faults():
    base = default_camera("MS")
    design = merge.merged({"recommended": {"x": 1}}, answer_of(CHASE, PUSH), base=base, language="", model="m",
                          job_id="j", faults=["4C-1: names gear"])
    assert design["recommended"] == base.model_dump() and design["camera"]["state"] == "not designed"
    assert design["camera"]["faults"] == ["4C-1: names gear"] and not merge.designed(design)


def test_a_hold_has_no_speed_and_a_move_always_has_one():
    base = default_camera("MS")
    hold = merge.recommended_from({**answer_of(CHASE, "1Q-1")}, base)
    assert hold.movement == "Hold" and hold.speed == "None"
    move = merge.recommended_from({**answer_of(CHASE, PUSH), "speed": "none"}, base)
    assert move.speed == "Slow"


def test_the_sentence_is_the_agents_until_a_person_changes_a_field():
    base = default_camera("MS")
    design = merge.merged({}, answer_of(CHASE, PUSH), base=base, language="", model="m", job_id="j")
    rec = CameraSettings.model_validate(design["recommended"])
    assert words.sentence(rec, rec, design) == answer_of(CHASE, PUSH)["camera_sentence"].rstrip(".") + "."
    changed = rec.with_overrides({"movement": "Pull out"})
    said = words.sentence(changed, rec, design)
    assert "pulls back" in said and "dolly" not in said.lower()
    assert words.sentence(rec, rec, {}) == words.sentence_from_fields(rec)  # no agent design: code's words


def test_the_step_ops_round_trip():
    out = step.run({"op": "check", "answer": scene_answer(CHASE), "clips": CHASE["clips"]})
    assert out["faults"] == []
    clips = RUN4["clips"]
    b = step.run({"op": "brief", "scene_text": "<scene>x</scene>", "clips": clips[:1],
                  "ideas": {clips[0]["slate"]: [["push_in", "why"]]}})
    assert b["clips"].startswith("<clips>") and "push_in: why" in b["clips"]
    m = step.run({"op": "merge", "design": {}, "clip": answer_of(CHASE, PUSH),
                  "base": default_camera("MS").model_dump(),
                  "language": "l", "model": "m", "job_id": "j"})
    assert m["design"]["camera"]["state"] == "designed"
    with pytest.raises(ValueError):
        step.run({"op": "nothing"})
