"""Tests that live with the video_prompt step (plan/2026-11-20b §4): Api Denna E01-S04 as the product reads it
(`fixtures/e01_s04.json`, made by `lab/video_prompt/fixtures.py`) and gpt-6.1-sol's answers from lab run 003."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from hiru_ai.steps.video_prompt import logic, step

DATA = json.loads((Path(__file__).parent / "fixtures" / "e01_s04.json").read_text(encoding="utf-8"))
CLIPS, ANSWERS, PACKET = DATA["clips"], DATA["answers"], DATA["packet"]


def answer(slate: str) -> dict:
    return copy.deepcopy(ANSWERS[slate])


# ── the brief ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_scene_part_carries_who_each_line_is_said_to_its_intent_and_the_readers_note():
    text = logic.scene_brief({"packet": PACKET, "genre": "family drama", "style_note": ""})
    assert text.startswith("<scene>") and text.endswith("</scene>")
    assert "L11 Father (through the phone) to Anudi:" in text and "how (the reader's note):" in text
    assert "Father (heard on the phone only, never seen)" in text and "a Sri Lankan family drama" in text
    assert text == logic.scene_brief({"packet": PACKET, "genre": "family drama", "style_note": ""})  # same bytes


def test_the_clip_part_says_what_is_spoken_here_and_what_is_only_heard_over_it():
    two = logic.clip_brief(CLIPS["4A-2"])
    assert "- L5: Kasun, about 3.3 s of speech" in two and "Speech in all: about 6.6 s of a 6 s take." in two
    assert "Opens: on the accepted first frame" in two
    assert "a face sheet and a look sheet for Anudi" in two


def test_a_line_on_an_ambient_clip_is_heard_in_the_edit_and_never_spoken_in_it():
    """D7: today's serializer wrote speech into clips whose sound says nobody speaks (S05, S15)."""
    clip = next(c for c in CLIPS.values() if c["sound_mode"] == "ambient" and (c["lines"] or c["edit_lines"]))
    assert logic.spoken(clip) == []
    assert "Nobody speaks in this clip." in logic.clip_brief(clip)
    assert "Heard in the edit over this clip, NOT spoken in it" in logic.clip_brief(clip)
    made = logic.assemble(answer(clip["slate"]), clip)
    assert "Nobody speaks in this clip: no dialogue, no voice." in made["prose"]
    assert not any("sinhala" in seg for s in made["sections"] for seg in s["segments"])


def test_the_cards_follow_the_clip():
    assert logic.cards_for(CLIPS["4A-2"]) == ["dialogue", "sinhala_voice"]
    assert logic.cards_for(CLIPS["4E-2"]) == ["phone", "sinhala_voice"]
    assert "silent" in logic.cards_for(CLIPS["4H-1"])


# ── the gates: every answer sol wrote passes, and each gate catches its fault ───────────────────────────────────────


@pytest.mark.parametrize("slate", sorted(ANSWERS))
def test_every_final_answer_of_the_lab_passes_the_gates(slate: str):
    assert logic.gates(ANSWERS[slate], CLIPS[slate]) == []


def test_the_lines_must_be_the_clips_each_once_in_order():
    d = answer("4A-2")
    d["flow"] = [s for s in d["flow"] if s["line_id"] != "L6"]
    assert any(f.startswith("lines:") for f in logic.gates(d, CLIPS["4A-2"]))
    d = answer("4A-2")
    d["flow"][1], d["flow"][2] = d["flow"][2], d["flow"][1]
    assert any(f.startswith("lines:") for f in logic.gates(d, CLIPS["4A-2"]))


@pytest.mark.parametrize(("field", "bad", "fault"), [
    ("situation", "Kasun says ඔව් to her.", "Sinhala letters"),
    ("situation", "Kasun answers L5 to her.", "a line or block id (L5)"),
    ("people", 'Anudi, who said "thanks", stands left.', "quotation marks"),
    ("sound", "Rain; her words are heard in the edit over this shot.", "a note to us"),
    ("situation", "As the planner asked, they stand in the rain.", "a note to us"),
    ("camera", "A slow push-in on the two of them.", "moves it"),
    ("situation", "Blood on the road where he fell.", "decline"),
    ("sound", "rain " * 80, "characters, at most 250"),
])
def test_each_gate_catches_its_fault(field: str, bad: str, fault: str):
    d = answer("4A-2")
    d[field] = bad
    assert any(fault in f for f in logic.gates(d, CLIPS["4A-2"])), logic.gates(d, CLIPS["4A-2"])


def test_a_line_needs_a_delivery():
    d = answer("4A-2")
    next(s for s in d["flow"] if s["kind"] == "line")["how"] = ""
    assert "line L5: no delivery" in logic.gates(d, CLIPS["4A-2"])


def test_nobody_speaks_in_a_silent_clip():
    d = answer("4H-1")
    d["flow"][0]["text"] = "Kasun says goodbye quietly."
    assert any(f.startswith("nobody speaks in this clip") for f in logic.gates(d, CLIPS["4H-1"]))


def test_a_heard_voice_named_as_heard_passes_and_placed_in_frame_fails():
    d = answer("4E-2")
    d["people"] = "Anudi holds the phone to her ear. Father (heard only, never in frame) speaks through it."
    assert not any("only heard" in f for f in logic.gates(d, CLIPS["4E-2"]))
    d["people"] = "Anudi stands left; Father stands beside her."
    assert any("only heard and never in frame" in f for f in logic.gates(d, CLIPS["4E-2"]))


# ── the assembly ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_words_are_the_scripts_as_their_own_segment_and_the_sections_are_the_plans():
    made = logic.assemble(answer("4A-2"), CLIPS["4A-2"])
    assert [s["id"] for s in made["sections"]] == ["opening", "situation", "people", "action", "camera", "sound",
                                                   "rules", "format"]
    words = [seg["sinhala"] for s in made["sections"] for seg in s["segments"] if "sinhala" in seg]
    assert words == [ln["text"].strip().strip('"') for ln in CLIPS["4A-2"]["lines"]]
    assert "Kasun, to Anudi, friendly and modest" in made["prose"]
    assert {"label": "Lines verbatim from the script", "tone": "pass"} in made["checks"]
    assert {"label": "6.6 s of speech in a 6 s take", "tone": "advisory"} in made["checks"]
    assert "Image 1" not in made["prose"]  # the render cites the pictures it attaches


def test_a_phone_voice_is_heard_through_the_phone_and_mouthed_by_nobody():
    made = logic.assemble(answer("4E-2"), CLIPS["4E-2"])
    assert "Father's voice through the phone," in made["prose"]
    assert "No one on screen mouths these words." in made["prose"]
    assert {"label": "Heard only · Father (phone)", "tone": "pass"} in made["checks"]


def test_a_carried_over_shot_opens_on_the_last_frame_before_and_says_what_carries():
    clip = {**CLIPS["4A-2"], "opening": "The clip opens on the last frame of S04's take, which is supplied as its "
                                        "first frame.", "carried_from": "S04", "join": "", "carried": ""}
    made = logic.assemble(answer("4A-2"), clip)
    assert made["prose"].startswith("FIRST FRAME\nThe clip opens on the last frame of S04's take")
    assert {"label": "Starts on S04's last frame", "tone": "pass"} in made["checks"]


def test_a_matched_re_angle_says_so_with_what_it_carries_over():
    clip = {**CLIPS["4A-2"], "join": "This clip is a MATCHED RE-ANGLE of the previous one.",
            "carried": "Anudi holds the phone in her right hand"}
    first = logic.assemble(answer("4A-2"), clip)["sections"][0]["segments"][0]["text"]
    assert "MATCHED RE-ANGLE" in first and "Carried over: Anudi holds the phone in her right hand." in first


def test_a_repaired_answer_says_so():
    assert {"label": "Repaired once", "tone": "advisory"} in logic.assemble(answer("4A-2"), CLIPS["4A-2"],
                                                                            repaired=True)["checks"]


def test_the_step_runs_each_op():
    out = step.run({"op": "brief", "scene": {"packet": PACKET}, "clip": CLIPS["4A-2"]})
    assert set(out) == {"scene", "clip", "cards"}
    assert step.run({"op": "check", "direction": ANSWERS["4A-2"], "clip": CLIPS["4A-2"]}) == {"faults": []}
    assert set(step.run({"op": "assemble", "direction": ANSWERS["4A-2"], "clip": CLIPS["4A-2"]})) == {
        "sections", "prose", "checks"}
    with pytest.raises(ValueError):
        step.run({"op": "nothing"})


def test_a_phone_voice_is_not_said_to_come_through_the_phone_twice():
    """Live run 005: sol began the delivery with "Through the phone", and the head said it twice."""
    d = answer("4E-2")
    line = next(s for s in d["flow"] if s["kind"] == "line")
    line["how"] = "Through the phone, urgent and authoritative"
    prose = logic.assemble(d, CLIPS["4E-2"])["prose"]
    assert "Father's voice through the phone, urgent and authoritative:" in prose


@pytest.mark.parametrize(("said", "made"), [
    ("An eye-level medium shot on a 50mm lens, in a steady frame on a tripod.",
     "An eye-level medium shot on a 50mm lens, in a steady unmoving frame."),
    ("A close-up on a 65mm lens from a tripod at eye level.", "A close-up on a 65mm lens at eye level."),
    ("A tripod-mounted close-up.", "A locked-off close-up."),
])
def test_the_camera_section_names_no_gear(said: str, made: str):
    """Render 007 (360p, 2026-11-20): "a steady frame on a tripod" put a camera on a tripod into two takes."""
    d = answer("4A-2")
    d["camera"] = said
    camera = next(s for s in logic.assemble(d, CLIPS["4A-2"])["sections"] if s["id"] == "camera")
    assert camera["segments"][0]["text"] == made
