"""plan/2026-11-22c: a video note (how a shot plays) rewrites only the video prompt and keeps the drawn first frame."""
from __future__ import annotations

from contracts import picture_pins
from contracts.producer import VIDEO_NOTE_CHANGED, PersonEdits, Pins, default_camera, stale_reasons
from hiru_ai.agents.shot_prompter.agent import user_message
from hiru_ai.agents.shot_prompter.schema import Input
from hiru_ai.core import shot_prompts

CAM = default_camera("MS", heading="EXT. ROAD - DAY", time_of_day="DAY")
OPENING = {"people": [{"name": "Anudi", "side": "left", "facing": "Kamal", "posture": "standing", "hands": "phone in "
                       "her right hand", "expression": "worried"}], "background": "the road", "light": "noon sun"}


def made(note: str = "") -> Pins:
    return Pins(shot_version=3, script_hash="abc", picture=picture_pins.picture(CAM, None),
                motion=picture_pins.motion(CAM, None, None, note))


def reasons(pins: Pins, *, note: str, frame: bool = False) -> list[str]:
    now_motion = None if frame else picture_pins.motion(CAM, None, None, note)
    return stale_reasons(pins, shot_version=3, script_hash="abc", canon={},
                         picture=picture_pins.picture(CAM, None), motion=now_motion)


def test_a_new_note_marks_the_prompts_and_never_the_frame():
    assert reasons(made(), note="A softer, calmer voice.") == [VIDEO_NOTE_CHANGED]
    assert reasons(made(), note="A softer, calmer voice.", frame=True) == []  # a frame is compared on its picture


def test_the_same_note_is_current_and_a_cleared_note_is_a_change():
    assert reasons(made("A softer voice."), note="A  softer voice. ") == []  # whitespace is not a change
    assert reasons(made("A softer voice."), note="") == [VIDEO_NOTE_CHANGED]


def test_a_note_is_never_named_as_a_camera_move():
    said = reasons(made("Slow motion."), note="Faster.")
    assert said == [VIDEO_NOTE_CHANGED] and not any("camera" in r.lower() for r in said)


def test_a_pin_made_before_notes_existed_reads_as_no_note():
    old = Pins(shot_version=3, script_hash="abc", picture=picture_pins.picture(CAM, None),
               motion={k: v for k, v in picture_pins.motion(CAM, None, None).items() if k != "video_note"})
    assert reasons(old, note="") == []
    assert reasons(old, note="Slow motion.") == [VIDEO_NOTE_CHANGED]


def test_the_note_is_stored_only_when_set():
    assert PersonEdits(video_note="Slow motion.").dump() == {"video_note": "Slow motion."}
    assert PersonEdits().dump() == {}


class _World:
    """The frame_compose world as `needs` reads it: the stored prompt's reasons and the pins now."""

    def __init__(self, note: str) -> None:
        self.note = note

    def shot_prompt_reasons(self, row):
        record = row["design"]["shot_prompt"]
        return reasons(Pins.model_validate(record["pins"]), note=self.note)

    def pins_now(self, row):
        return {**made(self.note).model_dump(), "canon": {}, "looks": {}}


def test_a_note_alone_asks_for_a_video_only_rewrite():
    record = {"frame": {"composition": "x"}, "opening": OPENING, "pins": made().model_dump(),
              "video": {"flow": [{"start_s": 0, "end_s": 4}]}}
    row = {"design": {"shot_prompt": record}}
    assert shot_prompts.needs(_World(""), row) == "current"
    assert shot_prompts.needs(_World("A softer voice."), row) == "video_only"


def test_a_video_only_rewrite_needs_a_frame_drawn_from_the_stored_words():
    record = {"opening": OPENING}
    drawn = {"pins": {"picture": picture_pins.picture(CAM, None, picture_pins.opening_text(OPENING))}}
    assert shot_prompts.drawn_from(record, drawn)
    assert not shot_prompts.drawn_from(record, {"pins": {"picture": picture_pins.picture(CAM, None)}})  # code's words
    assert not shot_prompts.drawn_from(record, {"pins": None})  # uploaded, or the legacy engine
    other = {**OPENING, "light": "dusk"}
    assert not shot_prompts.drawn_from({"opening": other}, drawn)  # the words were rewritten since
    assert not shot_prompts.drawn_from(None, drawn)


def test_the_agent_reads_the_note_only_when_there_is_one():
    base = Input(scene="<scene/>", shot="<shot/>", camera="<camera/>", mode="video_only", fixed="{}")
    assert "video_note" not in user_message(base)
    text = user_message(base.model_copy(update={"video_note": "A softer, calmer voice."}))
    assert "<video_note>\nA softer, calmer voice.\n</video_note>" in text
    assert text.index("<video_note>") < text.index("<fixed>")  # the fixed frame words still close the message
