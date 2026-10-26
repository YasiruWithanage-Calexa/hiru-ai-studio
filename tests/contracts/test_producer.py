"""contracts.producer: the camera vocabulary, pins and staleness, the frame prompt, prompt text."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from contracts.producer import (
    CAMERA_OPTIONS,
    CameraField,
    CameraSettings,
    CameraUpdate,
    CastMember,
    PromptSection,
    PromptSegment,
    camera_checks,
    cast_in,
    default_camera,
    frame_prompt,
    lighting_for,
    pins_for,
    prompt_text,
    script_hash,
    stale_reasons,
    storyboard_note,
)
from contracts.shotplan import Item

KAMALA = CastMember(id="k", code="C01", name="Kamala", version=2, wardrobe_anchor="a faded blue saree",
                    appearance="52, grey hair in a bun", voice_pin="low voice")
NIMAL = CastMember(id="n", code="C02", name="Nimal", version=1)
CHARACTERS = [{"id": "k", "name": "Kamala", "aliases": ["Amma"]}, {"id": "n", "name": "Nimal", "aliases": []}]
SCENE = {"heading": "INT. KAMALA'S HOUSE - KITCHEN - DAWN", "time_of_day": "DAWN", "location_id": "h"}


def items() -> list[Item]:
    return [Item(0, "action", "Amma stirs the pan by the fire."),
            Item(1, "dialogue", "අම්මේ, මම ආපහු ආවා.", "Nimal", "n", "quietly", "l1")]


@pytest.mark.parametrize(("heading", "time", "preset"), [
    ("INT. HOUSE - NIGHT", "", "Night, lamp key"), ("EXT. HARBOUR - NIGHT", "NIGHT", "Night, moonlight"),
    ("INT. KITCHEN - DAWN", "DAWN", "Dawn, soft ambient"), ("EXT. YARD - EVENING", "EVENING", "Dusk, soft ambient"),
    ("EXT. HARBOUR - DAY", "DAY", "Day, open sun"), ("INT. SHED - DAY", "", "Day, window light"),
])
def test_lighting_from_the_heading(heading, time, preset):
    assert lighting_for(heading, time) == preset


def test_default_camera_keeps_the_directors_size_and_is_valid_everywhere():
    for code in ("WIDE", "MS", "MCU", "CU", "TWO", "OTS", "INSERT"):
        cam = default_camera(code, heading="INT. X - DAY")
        assert cam.movement == "Static" and cam.speed == "None" and cam.axis.startswith("Side A")
    assert default_camera("CU").framing == "Close-up" and default_camera("CU").lens == "85mm"


def test_every_field_is_one_of_the_panels_choices():
    with pytest.raises(ValidationError):
        CameraSettings(**{**default_camera("MS").model_dump(), "lens": "300mm"})
    with pytest.raises(ValidationError):
        CameraUpdate(lens="300mm")
    assert set(CAMERA_OPTIONS) == set(CameraField)
    cam = default_camera("MS").with_overrides({"lens": "85mm", "speed": "Warp", "nonsense": "x"})
    assert cam.lens == "85mm" and cam.speed == "None", "an unknown choice is ignored, not fatal"


def test_storyboard_note():
    cam = default_camera("MCU")
    assert storyboard_note(cam) == "50mm · static"
    assert storyboard_note(cam.with_overrides({"movement": "Dolly in", "speed": "Slow"})) == "50mm · slow dolly in"


def test_cast_comes_from_the_lines_and_the_names_in_the_action():
    assert cast_in(items(), CHARACTERS) == ["k", "n"], "Kamala by her alias in the action, Nimal by his line"
    assert cast_in(items()[1:], CHARACTERS) == ["n"]


def test_pins_and_why_something_is_stale():
    pins = pins_for(shot_version=2, scene=SCENE, items=items(), cast_ids=["k", "n"], versions={"k": 2, "n": 1, "h": 1})
    assert pins.canon == {"k": 2, "n": 1, "h": 1}
    canon = {"k": KAMALA, "n": NIMAL, "h": CastMember(id="h", code="L01", name="Kamala's house", kind="location",
                                                       version=1)}
    now = dict(shot_version=2, script_hash=pins.script_hash, canon=canon)
    assert stale_reasons(pins, **now) == []
    assert stale_reasons(None, **now) == []
    assert stale_reasons(pins, **{**now, "shot_version": 3}) == ["The shot changed (its length, size, sound or join)."]
    edited = script_hash(SCENE, [Item(0, "action", "Amma stirs the pan. Rain."), items()[1]])
    assert stale_reasons(pins, **{**now, "script_hash": edited}) == ["The script for this shot changed."]
    newer = {**canon, "k": KAMALA.model_copy(update={"version": 3})}
    assert stale_reasons(pins.model_dump(), **{**now, "canon": newer}) == [
        "C01 Kamala has a new card (v3; this used v2)."]
    gone = {k: v for k, v in canon.items() if k != "n"}
    assert stale_reasons(pins, **{**now, "canon": gone}) == ["Someone in this shot was removed from the canon."]
    moved = {**SCENE, "location_id": "elsewhere"}
    assert script_hash(moved, items()) != pins.script_hash, "a new place is a new shot"


def test_the_frame_prompt_names_references_by_position_and_honours_a_persons_framing():
    cam = default_camera("WIDE", heading="INT. X - NIGHT").with_overrides({"framing": "Close-up", "lens": "85mm"})
    text = frame_prompt(ir={"setting": "the kitchen", "first_frame": {"composition": "Kamala at the stove",
                                                                      "subjects": ["Kamala"]}},
                        camera=cam, aspect_ratio="9:16", cast=[KAMALA],
                        references=["the character sheet for Kamala", "the location plate for the house"],
                        recommended_framing="Wide shot")
    assert "image 1 is the character sheet for Kamala; image 2 is the location plate" in text
    assert "Close-up, eye level, 85mm lens at f/4" in text and "Compose it as a close-up." in text
    assert "Kamala: 52, grey hair in a bun; wearing a faded blue saree" in text
    assert text.endswith("no collage, no split panels.") and "9:16 vertical framing" in text
    assert "Night, lamp key" in text, "the preset lights a frame the IR says nothing about"


def test_camera_checks_follow_the_axis_and_the_cards():
    a = default_camera("WIDE")
    b = a.with_overrides({"axis": "Side B · right to left"})
    checks = camera_checks(index=1, cameras=[a, b], framing="WIDE", sound_mode="dialogue", cast=[KAMALA, NIMAL],
                           speaker_ids=["n"], frame_strategy="generate")
    labels = [c.label for c in checks]
    assert labels[0] == "Crosses the axis · Side B (unlike S01)"
    assert "Speaker is hard to see in this size" in labels
    assert "Wardrobe · Kamala" in labels and "No wardrobe anchor · Nimal" in labels and "No voice pin · Nimal" in labels


def test_prompt_text_matches_the_frontends_prompt_to_text():
    sections = [PromptSection(id="a", title="Action & dialogue",
                              segments=[PromptSegment(text='He says, "'), PromptSegment(sinhala="අම්මේ"),
                                        PromptSegment(text='"')]),
                PromptSection(id="f", title="Format", segments=[PromptSegment(text="16:9.")])]
    assert prompt_text(sections) == 'ACTION & DIALOGUE\nHe says, "අම්මේ"\n\nFORMAT\n16:9.'
    assert sections[0].segments[1].model_dump() == {"sinhala": "අම්මේ"}
    with pytest.raises(ValidationError):
        PromptSegment(text="x", sinhala="y")
