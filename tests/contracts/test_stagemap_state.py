"""The scene state ledger (plan/2026-11-09 phase 1): the stager's new fields, validated entry by entry, and the state at
any block, worked out by code from the map. A map written before the ledger reads exactly as it did."""

from __future__ import annotations

import json
from pathlib import Path

from contracts import holding as hd
from contracts import stagemap as sm
from contracts.shotplan import Item

FIXTURES = Path(__file__).resolve().parents[1] / "raphael" / "fixtures"


def items() -> list[Item]:
    from tests.raphael import gold

    return gold.scene().items()


def gold_raw() -> dict:
    return json.loads((FIXTURES / "staging.json").read_text(encoding="utf-8"))


def gold_map() -> sm.SceneStaging:
    return sm.validate(gold_raw(), items(), ["Kasun", "Anudi"], version=1, by="person")


def mark(**kw) -> dict:
    return {"block": 1, "who": "Kasun", "zone": "stall counter", "facing": "", "frame_side": "", "holding": "", **kw}


def answer(*marks: dict, props: list[dict] | None = None) -> dict:
    return {"zones": ["stall counter", "pavement"], "marks": list(marks), "props": props or []}


def made(raw: dict) -> sm.SceneStaging:
    return sm.validate(raw, items(), ["Kasun", "Anudi"], version=1, by="model")


# ── validation ──────────────────────────────────────────────────────────────────────────────


def test_an_old_map_reads_and_validates_exactly_as_before():
    old = {"zones": ["stall counter", "pavement"], "marks": [mark(holding="the phone")]}
    staging = made(old)
    m = staging.marks[0]
    assert (m.posture, m.left_hand, m.right_hand, m.condition, m.wearing) == ("", "", "", "", "")
    assert staging.props == []
    assert staging.text() == (
        "Spots: stall counter, pavement\nFrom block 1: Kasun in the stall counter, holding the phone"
    )
    stored = sm.SceneStaging.model_validate({"zones": ["a", "b"], "marks": [mark(zone="a")], "by": "model"})
    assert stored.props == [] and stored.marks[0].posture == ""


def test_a_junk_posture_is_dropped_to_empty_and_the_mark_is_kept():
    staging = made(answer(mark(posture="levitating"), mark(block=6, posture="Running")))
    assert [m.posture for m in staging.marks] == ["", "running"]


def test_a_named_hand_is_added_to_holding_when_it_is_missing():
    staging = made(answer(mark(holding="umbrella", right_hand="the phone", left_hand="umbrella")))
    m = staging.marks[0]
    assert m.holding == "umbrella, the phone"
    assert {t.key for t in hd.things_of(m.holding)} == {"umbrella", "phone"}
    assert made(answer(mark(left_hand="nothing"))).marks[0].left_hand == ""


def test_condition_and_wearing_are_cut_to_their_length():
    m = made(answer(mark(condition="x" * 90, wearing="y" * 200))).marks[0]
    assert len(m.condition) == 40 and len(m.wearing) == 80


def test_a_prop_mark_must_name_a_block_that_exists_and_a_thing():
    staging = made(answer(mark(), props=[{"block": 99, "prop": "phone", "where": "on the ground", "state": ""},
                                         {"block": 2, "prop": "—", "where": "nowhere", "state": ""},
                                         {"block": 2, "prop": "tea flask", "where": "on the counter", "state": ""},
                                         {"block": 2, "prop": "the flask", "where": "twice", "state": ""}]))
    assert [(p.block, p.prop) for p in staging.props] == [(2, "tea flask")]


def test_a_prop_mark_at_the_block_a_person_still_holds_it_is_dropped():
    staging = made(answer(mark(block=6, holding="phone"),
                          props=[{"block": 6, "prop": "phone", "where": "on the ground", "state": ""}]))
    assert staging.props == []


def test_a_prop_mark_after_a_hand_took_it_gives_the_holder_a_mark_without_it():
    staging = made(answer(mark(block=6, zone="pavement", holding="phone, umbrella", right_hand="phone",
                               posture="running"),
                          props=[{"block": 9, "prop": "phone", "where": "on the bench", "state": ""}]))
    at9 = [m for m in staging.marks if m.block == 9]
    assert len(at9) == 1 and at9[0].who == "Kasun"
    assert at9[0].holding == "umbrella" and at9[0].right_hand == "" and at9[0].posture == "running"
    assert at9[0].zone == "pavement"
    assert len(staging.props) == 1


def test_no_zones_means_no_marks_and_no_props():
    raw = {"zones": ["only one"], "marks": [mark(zone="only one")],
           "props": [{"block": 1, "prop": "phone", "where": "x", "state": ""}]}
    staging = made(raw)
    assert staging.marks == [] and staging.props == []


# ── the state at a block ────────────────────────────────────────────────────────────────────


def test_the_state_follows_the_handover_and_the_dropped_phone():
    staging, its = gold_map(), items()
    at4 = sm.state_at(staging, its, 4)
    assert at4.person("Anudi").hand_of("phone") == "left"
    assert at4.prop_text("phone") == "phone: Anudi's left hand"
    at5 = sm.state_at(staging, its, 5)
    assert "phone" not in at5.person("Anudi").keys()
    assert at5.prop_text("phone") == "phone: on the ground by the three-wheeler"
    at7 = sm.state_at(staging, its, 7)
    assert at7.person_text("Kasun") == "Kasun: running, at the pavement, phone in right hand"
    assert at7.prop_text("phone") == "phone: Kasun's right hand"
    at9 = sm.state_at(staging, its, 9)
    assert at9.person("Kasun").keys() == set() and at9.person("Anudi").hand_of("phone") == "left"
    assert at9.prop_text("phone") == "phone: Anudi's left hand"
    assert sm.state_at(staging, its, 21).person_text("Anudi") == "Anudi: off"


def test_posture_and_condition_hold_until_a_mark_changes_them_and_well_ends_a_condition():
    staging = made(answer(mark(block=1, posture="lying", condition="unconscious"), mark(block=6),
                          mark(block=9, condition="well", posture="sitting")))
    its = items()
    assert sm.state_at(staging, its, 7).person_text("Kasun") == "Kasun: lying, at the stall counter, unconscious"
    assert sm.state_at(staging, its, 9).person_text("Kasun") == "Kasun: sitting, at the stall counter"


def test_nobody_is_in_the_state_before_their_first_mark_and_no_map_is_an_empty_state():
    staging, its = gold_map(), items()
    assert not sm.state_at(staging, its, 0)
    assert sm.state_at(staging, its, 3).person("Anudi") is None
    assert not sm.state_at(None, its, 5)
    assert sm.delta_text(sm.state_at(None, its, 4), sm.state_at(None, its, 5)) == ""


def test_a_person_phrase_is_at_most_state_chars():
    staging = made(answer(mark(holding=", ".join(f"thing{i}" for i in range(9)), condition="soaked to the skin",
                               wearing="a very long coat " * 4, posture="standing")))
    assert len(sm.state_at(staging, items(), 1).person_text("Kasun")) <= sm.STATE_CHARS


def test_the_delta_says_only_what_changed():
    staging, its = gold_map(), items()

    def delta(b: int) -> str:
        return sm.delta_text(sm.state_at(staging, its, b - 1), sm.state_at(staging, its, b))

    assert delta(5) == ("Anudi: walking, at the pavement, umbrella in right hand, carrying the handbag; "
                        "phone: on the ground by the three-wheeler")
    assert delta(6) == "Kasun: running, at the pavement, phone in right hand"
    assert delta(9) == ("Kasun: hands empty; Anudi: phone in left hand, umbrella in right hand, carrying the "
                        "handbag")
    assert delta(10) == ""
    assert delta(21) == "Anudi: off"


def test_a_clip_opens_with_the_state_before_its_first_block_and_ends_after_its_last():
    staging, its = gold_map(), items()
    opens, ends = sm.clip_state(staging, its, [9, 8])
    assert opens.prop_text("phone") == "phone: Kasun's right hand"
    assert ends.prop_text("phone") == "phone: Anudi's left hand"
    # someone who comes in at the clip's first block opens as they arrive
    opens, _ = sm.clip_state(staging, its, [4, 5])
    assert opens.person("Anudi").hand_of("umbrella") == "right"
    assert sm.clip_state(staging, its, []) == (sm.SceneState(), sm.SceneState())


def test_pinned_writes_the_map_for_another_copy_of_the_same_blocks():
    from dataclasses import replace

    from contracts import reading as rd

    real = [replace(i, line_id=f"real-{i.index}") if i.is_line else i for i in items()]
    staging = sm.validate(gold_raw(), real, ["Kasun", "Anudi"], version=1, by="person")
    onto = items()  # the same blocks, the lines under their short ids
    assert rd.basis(onto) != staging.basis
    pin = sm.pinned(staging, real, onto)
    assert pin.basis == rd.basis(onto) and pin.written_at is None
    assert [(m.block, m.who) for m in pin.marks] == [(m.block, m.who) for m in staging.marks]
    assert sm.state_at(pin, onto, 9).prop_text("phone") == sm.state_at(staging, real, 9).prop_text("phone")
    assert [p.block for p in pin.props] == [1, 5]


# ── the hands sentence names the hand when the mark does ────────────────────────────────────


def test_the_hands_sentence_says_the_hand_a_mark_names():
    ledger = sm.ledger_of(gold_map(), items())
    hands = hd.shot_hands(ledger, block_start=10, block_end=12, seen=["Anudi", "Kasun"])
    assert "Anudi holds the phone in the left hand and the umbrella in the right hand" in hands.sentence


def test_a_mark_without_a_hand_reads_as_before():
    ledger = hd.Ledger.of([{"block": 0, "who": "Kasun", "holding": "the phone"}])
    assert hd.shot_hands(ledger, block_start=1, block_end=2, seen=["Kasun"]).sentence == (
        "Hands: Kasun holds the phone in one hand.")
    two = hd.Ledger.of([{"block": 0, "who": "Kasun", "holding": "phone, umbrella", "right_hand": "phone"}])
    assert "the phone in the right hand and the umbrella in the other hand" in hd.shot_hands(
        two, block_start=1, block_end=2, seen=["Kasun"]).sentence
