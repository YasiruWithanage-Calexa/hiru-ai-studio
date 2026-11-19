"""The coverage fixes of 2026-11-18 (lab/coverage): what five Omni Flash takes of one phone drop taught, held by code.

Api Denna v2, Episode 1, Scene 3, with the stager's real marks: Anudi walks with her umbrella and phone (b0), the phone
falls (b1), Kasun picks it up and runs (b2), calls out (b3), holds it out to her (b4). Raphael, with the coverage rule,
planned the fall as an insert (b0-b1) and her walking on as a separate clip (b1 only) that opens with the phone already
on the road. No model is called.
"""

from __future__ import annotations

from typing import Any

from contracts.camera_words import lighting_words
from contracts.holding import Ledger, hands_for, shot_hands, thing_of, things_of
from contracts.producer import default_camera
from contracts.raphael.wire import SoundW
from hiru_ai.core import parts
from hiru_ai.steps.serialize.schema import get_schema

raphael_write = parts.step("raphael_write", "logic")
shots_mod = parts.step("serialize", "shots")
serialize = parts.step("serialize", "logic")


def mark(block: int, who: str, holding: str) -> dict[str, Any]:
    return {"block": block, "who": who, "zone": "roadside", "facing": "", "frame_side": "", "holding": holding}


# the stager's marks for E01-S03 (lab/llm_reader/runs/e2e/03_memory.json)
MARKS = [mark(0, "Anudi", "umbrella, smartphone"), mark(0, "Kasun", ""), mark(1, "Anudi", "umbrella"),
         mark(2, "Kasun", "smartphone"), mark(4, "Anudi", "umbrella"),
         mark(4, "Kasun", "smartphone, held out toward Anudi")]
SCENE = {"id": "s3", "production_id": "p", "script": [{"kind": "action", "text": "x"}] * 5,
         "staging": {"zones": ["roadside"], "marks": MARKS, "props": []}}


def shot(number: int, a: int, b: int, *, stage: int = 1, card: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": f"s{number}", "number": number, "block_start": a, "block_end": b, "stage": stage, "framing": "MS",
            "planner": "raphael", "card": card or {"size": "MS"}}


# ── the ledger ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_how_a_thing_is_held_is_never_read_as_a_thing():
    assert thing_of("held out toward Anudi") is None
    assert [t.key for t in things_of("smartphone, held out toward Anudi")] == ["smartphone"]
    assert [t.key for t in things_of("phone raised up high")] == ["phone"]
    assert [t.key for t in things_of("umbrella, phone")] == ["umbrella", "phone"]  # as before


def test_kasun_holding_the_phone_out_takes_nobody():
    hands = shot_hands(Ledger.of(MARKS), block_start=4, block_end=5, seen=["Kasun", "Anudi"], video=True)
    assert "takes the anudi" not in hands.sentence.lower()
    assert "Kasun holds the smartphone" in hands.sentence and not hands.moves


def test_a_hand_that_lets_go_in_the_shot_is_not_told_to_keep_what_it_holds():
    """Take 1 and 2: "each hand keeps its own, neither is put down" beat the drop."""
    drop = shot_hands(Ledger.of(MARKS), block_start=0, block_end=2, seen=["Anudi"], video=True)
    assert "lets go of the smartphone" in drop.sentence and drop.moves
    assert "neither is put down" not in drop.sentence
    before = shot_hands(Ledger.of(MARKS), block_start=0, block_end=1, seen=["Anudi"], video=True)
    assert "neither is put down" in before.sentence and not before.moves  # nothing leaves a hand: as before


def test_the_second_half_of_a_split_moment_opens_after_it():
    """Take 3: the text must not contradict the first frame. Her walking on opens with the phone already down."""
    plain = hands_for(SCENE, shot(2, 1, 2), ["Anudi"], video=True)
    assert "holds the smartphone" in plain.sentence and "lets go" in plain.sentence  # today: the phone back in hand
    after = hands_for(SCENE, shot(2, 1, 2, card={"size": "MS", "after": True}), ["Anudi"], video=True)
    assert after.sentence == "Hands: Anudi holds the umbrella in one hand." and not after.moves


def test_raphael_write_marks_the_walk_on_after_the_insert_and_nothing_else():
    shots = [shot(1, 0, 2), shot(2, 1, 2), shot(3, 0, 0, stage=2), shot(4, 2, 3), shot(5, 3, 4), shot(6, 4, 5)]
    raphael_write.mark_after(shots, SCENE)
    assert [s["number"] for s in shots if s["card"].get("after")] == [2]


def _plan(rows: list[dict[str, Any]], upsert: list[dict[str, Any]]) -> Any:
    from hiru_ai.core.coverage_rows import Plan

    return Plan(upsert=upsert, removed=[], lines=[], rows=rows, all_lines=[], designs=[],
                touched=[str(r["id"]) for r in upsert])


def test_an_edit_that_moves_the_walk_on_off_the_moment_clears_its_mark():
    """plan/2026-11-18b phase 8: Zora or Sable moves the walk-on to b2; it no longer opens after the drop."""
    from hiru_ai.core.coverage_rows import remark_after

    moved = {**shot(2, 2, 3, card={"size": "MS", "after": True}), "version": 3}
    plan = _plan([shot(1, 0, 2), moved], [moved])
    remark_after(SCENE, plan, now="t")
    assert "after" not in plan.rows[1]["card"]
    assert plan.upsert[0] is plan.rows[1] and plan.rows[1]["version"] == 3  # already touched: one bump, by the save


def test_a_new_walk_on_clip_after_the_insert_is_marked_and_an_untouched_one_is_written_too():
    from hiru_ai.core.coverage_rows import remark_after

    new = {**shot(2, 1, 2), "version": 1}
    plan = _plan([shot(1, 0, 2), new], [new])
    remark_after(SCENE, plan, now="t")
    assert plan.rows[1]["card"]["after"] is True and plan.upsert == [plan.rows[1]]
    # the insert is merged away: the walk-on's mark goes, and the untouched row is written with its version bumped
    kept = {**shot(1, 1, 2, card={"size": "MS", "after": True}), "version": 4}
    plan = _plan([kept], [])
    remark_after(SCENE, plan, now="t")
    assert "after" not in plan.rows[0]["card"] and plan.rows[0]["version"] == 5 and plan.upsert == [plan.rows[0]]
    assert plan.touched == ["s1"]


# ── the prompt ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_shot_where_a_thing_leaves_a_hand_drops_objects_stay_put_and_only_that():
    rules = get_schema()
    assert rules.rule("stay_put") in rules.rule("physics")  # the sentence the guard takes out is really there

    class Shot:
        def __init__(self, moves: bool) -> None:
            self.seen, self.moves = [object()], moves

    moving, still = serialize._guard(Shot(True)), serialize._guard(Shot(False))
    assert rules.rule("stay_put") not in moving and rules.rule("stay_put") in still
    assert "Gravity behaves normally" in moving and "impenetrable" in moving


def test_each_beat_lands_once_in_the_window_it_overlaps_most():
    """3G-1 in the saved plan: the phone fell twice and 'the phone rests on the roadside' was dropped."""
    got = [{"time": "0-1s", "action": "Her hand nears the pocket.", "performance": "Eyes ahead."},
           {"time": "1-4s", "action": "The phone slips and falls.", "performance": "She walks on."},
           {"time": "4-5s", "action": "The phone rests on the roadside.", "performance": ""},
           {"time": "5-6s", "action": "The phone remains still.", "performance": ""}]
    placed = shots_mod._placed(got, [(0, 3), (3, 6)])
    assert placed is not None
    assert [p["action"].count("falls") for p in placed] == [1, 0]
    assert placed[0]["action"] == "Her hand nears the pocket. Eyes ahead. The phone slips and falls."
    assert placed[0]["performance"] == "She walks on."
    assert placed[1]["action"] == "The phone rests on the roadside. The phone remains still."


def test_a_window_no_beat_starts_in_is_empty_and_untimed_beats_are_mapped_as_before():
    one = [{"time": "0-6s", "action": "She walks.", "performance": ""}]
    assert shots_mod._placed(one, [(0, 3), (3, 6)]) == [one[0], {}]
    assert shots_mod._placed([{"action": "x"}], [(0, 4)]) is None


def test_a_call_for_silence_with_rain_keeps_the_rain():
    """Raphael's `silence` means nobody speaks; 'Silence, no room tone' took the rain out of a rain scene."""
    clip = type("C", (), {"lines": [], "sound": SoundW(ambience="Light rain.", effects="", music="", silence=True)})()
    assert raphael_write.sound_mode_of(clip, False, False) == "ambient"
    clip.sound = SoundW(ambience="", effects="", music="", silence=True)
    assert raphael_write.sound_mode_of(clip, False, False) == "silent"


def test_the_sound_line_ends_once_and_leaves_out_what_is_not_there():
    card = parts.step("serialize", "card")
    said = card.sound_text({"sound": {"ambience": "Light rain and distant traffic.", "effects": "None added.",
                                      "music": "None; scoped silence, no score.", "silence": True}})
    assert said == "room: Light rain and distant traffic"
    assert card.sound_text({"sound": {"ambience": "Rain.", "effects": "A small phone landing.", "music": ""}}) == (
        "room: Rain; effects: A small phone landing")


def test_the_planners_light_says_the_source_and_the_preset_only_the_time():
    """A heading with no INT or EXT gave 'Day, window light' on an open road."""
    cam = default_camera("MS", heading="SCENE 03 — THE UNEXPECTED ENCOUNTER", time_of_day="DAY")
    assert cam.lighting == "Day, window light"
    light = "Overcast daylight from the open road"
    assert lighting_words(cam, cam, f"{light}.") == f"Day: {light}."
    assert lighting_words(cam, cam, "") == "Day, window light."
