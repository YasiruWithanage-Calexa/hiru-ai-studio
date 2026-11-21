"""plan/2026-11-20d D8: one picture pin, one motion pin, and the reasons that name each field that moved."""
from __future__ import annotations

from contracts import picture_pins
from contracts.producer import BEFORE_CAMERA, OPENING_REWRITTEN, Pins, camera_changes, default_camera, stale_reasons

DESIGN = {"state": "designed", "opens_on": "waist-up on Anudi, left third", "lands_on": "chest-up", "end_size": "MCU",
          "start_s": 1.0, "end_s": 4.5, "trigger": "L4", "camera_sentence": "The camera moves slowly toward her."}


def cam(**changes: str):
    base = default_camera("MS", heading="EXT. ROAD - DAY", time_of_day="DAY")
    return base.model_copy(update=changes)


def pins(**extra) -> Pins:
    return Pins(shot_version=1, script_hash="abc", **extra)


def reasons(made: Pins, *, picture=None, motion=None) -> list[str]:
    return stale_reasons(made, shot_version=1, script_hash="abc", canon={}, picture=picture, motion=motion)


def test_an_angle_and_height_change_names_both_fields_before_and_after():
    was = picture_pins.picture(cam(angle="Eye level", height="Eye"), DESIGN)
    now = picture_pins.picture(cam(angle="Low", height="Hip"), DESIGN)
    assert reasons(pins(picture=was), picture=now) == ["The camera changed: angle eye level → low; height eye → hip."]


def test_a_move_only_change_keeps_the_frame_but_not_the_video_prompt():
    still = picture_pins.picture(cam(), DESIGN)
    was = picture_pins.motion(cam(movement="Push in", speed="Slow"), None, DESIGN)
    now = picture_pins.motion(cam(movement="Hold", speed="None"), None, DESIGN)
    frame = pins(picture=still)
    prompt = pins(picture=still, motion=was)
    assert reasons(frame, picture=picture_pins.picture(cam(), DESIGN)) == []  # the frame: picture only
    said = reasons(prompt, picture=still, motion=now)
    assert said and said[0].startswith("The camera move changed: move push in → hold; speed slow → none")


def test_the_design_opening_and_long_texts_are_named_not_shown():
    was = picture_pins.picture(cam(), DESIGN)
    now = picture_pins.picture(cam(), {**DESIGN, "opens_on": "full figure, centre"})
    assert reasons(pins(picture=was), picture=now) == ["The camera changed: opening picture changed."]
    assert len(was["opens_on"]) == 12 and "Anudi" not in was["opens_on"]


def test_a_frame_drawn_from_a_shot_prompt_is_out_of_date_when_the_opening_is_rewritten():
    one = {"people": [{"name": "Anudi", "side": "left", "facing": "Kasun", "posture": "standing", "hands": "phone",
                       "expression": "warm"}], "background": "stall", "light": "overcast"}
    two = {**one, "people": [{**one["people"][0], "side": "right"}]}
    frame = pins(picture=picture_pins.picture(cam(), DESIGN, picture_pins.opening_text(one)))
    assert reasons(frame, picture=picture_pins.picture(cam(), DESIGN, picture_pins.opening_text(one))) == []
    assert reasons(frame, picture=picture_pins.picture(cam(), DESIGN, picture_pins.opening_text(two))) == [
        OPENING_REWRITTEN]
    # a frame drawn with no shot prompt pins no opening: writing one later does not mark it
    plain = pins(picture=picture_pins.picture(cam(), DESIGN))
    assert reasons(plain, picture=picture_pins.picture(cam(), DESIGN, picture_pins.opening_text(one))) == []


def test_an_older_pin_without_picture_or_motion_is_out_of_date_only_once_the_camera_agent_designed_the_shot():
    """The audit of 2026-11-21: a frame of 18 November and a legacy "tripod, does not move at all" prompt passed as
    current after the Camera agent designed tilt up, lead and push."""
    now = {"picture": picture_pins.picture(cam(angle="Low"), DESIGN),
           "motion": picture_pins.motion(cam(), None, DESIGN)}
    assert reasons(pins(), **now) == []  # no Camera agent design: nothing to compare against
    assert camera_changes({}, {"angle": "Low"}, head="x") == []
    made_before = stale_reasons(pins(), shot_version=1, script_hash="abc", canon={}, designed=True, **now)
    assert made_before == [BEFORE_CAMERA]
    frame_before = stale_reasons(pins(), shot_version=1, script_hash="abc", canon={}, designed=True,
                                 picture=now["picture"])
    assert frame_before == [BEFORE_CAMERA]
    pinned = pins(picture=now["picture"], motion=now["motion"])
    assert stale_reasons(pinned, shot_version=1, script_hash="abc", canon={}, designed=True, **now) == []


def test_a_persons_camera_change_moves_the_sentence_in_the_motion_pin():
    agent = picture_pins.motion(cam(), cam(), DESIGN)
    person = picture_pins.motion(cam(lens="85mm"), cam(), DESIGN)  # any change: code's sentence replaces the agent's
    assert agent["sentence"] != person["sentence"]


def test_pinned_adds_both_to_the_stored_pins():
    out = picture_pins.pinned(pins(), cam(), None, DESIGN)
    assert set(out["picture"]) >= {"framing", "angle", "height", "opens_on"} and out["motion"]["trigger"] == "L4"
    assert Pins.model_validate(out).picture == out["picture"]
