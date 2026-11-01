"""A scene's reading and the time it gives the kernel (plan/2026-11-01d, Phases 1 and 2)."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from contracts import bridges, reading, sceneplan
from contracts.shotplan import (
    LEAD_IN_S,
    LINE_GAP_S,
    TAIL_S,
    Item,
    ProposedShot,
    fit,
    line_seconds,
    shot_clock,
)
from contracts.timing import BREATH_BAND, HOLD_RANGE_S, TURN_GAP_S
from tests.services import scene2_fixture as scene2

CAST = ["Kasun", "Anudi", "Anudi's Father"]


def scene2_items() -> list[Item]:
    script = bridges.with_bridges(scene2.blocks(screens=True), scene2.lines(), 1, CAST)
    return sceneplan.items_for(script, scene2.lines())


def at(items: list[Item], text: str) -> int:
    return next(i.index for i in items if text in i.text)


def say(index: int, who: str, words: int = 4, **extra: Any) -> Item:
    return Item(index, "dialogue", " ".join(["word"] * words), who, who, "", f"l{index}", **extra)


def act(index: int, text: str = "Something happens.", **extra: Any) -> Item:
    return Item(index, "action", text, screen="act", **extra)


# ── the constants (mirrored in the interface's timing.ts) ───────────────────────────────────


def test_feelings_time_constants():
    assert HOLD_RANGE_S == (1.0, 3.0) and TURN_GAP_S == 1.0 and BREATH_BAND == (0.15, 0.30)
    assert TURN_GAP_S > LINE_GAP_S


# ── Phase 1: the free reading ───────────────────────────────────────────────────────────────


def test_the_rules_reading_of_scene_2_finds_the_call_and_the_look_and_ends_on_kasun():
    items = scene2_items()
    r = reading.by_rules(items, CAST, version=1)
    call, look = at(items, "Anudi, where are you"), at(items, "She looked at Kasun")
    watched = at(items, "watched her go")
    assert r.by == "rules" and r.for_version == 1 and r.basis == reading.basis(items)
    assert [u.turn_block for u in r.units if u.turn_block is not None][-2:] == [call, look]
    # the call is heard by whoever holds the phone, the look is Anudi's own
    reactions = {b.after_block: (b.who, b.priority, b.seconds) for b in r.breath if b.kind == "reaction"}
    assert reactions[call] == ("Anudi", 1, 1.5) and reactions[look] == ("Anudi", 1, 1.5)
    buttons = [b for b in r.breath if b.kind == "button"]
    assert len(buttons) == 1 and buttons[0].after_block == watched and buttons[0].who == "Kasun"
    # a thought nobody can film stays narration, with a reason
    note = at(items, "no idea")
    assert [(t.block, t.narration_only, bool(t.reason)) for t in r.subtext] == [(note, True, True)]


def test_a_script_with_no_reaction_or_arrival_reads_with_no_breath():
    items = [act(0, "A kettle boils."), say(1, "Nimal"), say(2, "Kamala"), act(3, "The kettle is lifted off.")]
    r = reading.by_rules(items, ["Nimal", "Kamala"], version=2)
    assert r.breath == [] and r.units == [] and r.for_version == 2


def test_a_model_answer_is_checked_entry_by_entry_and_invalid_entries_are_dropped():
    items = scene2_items()
    call, look = at(items, "Anudi, where are you"), at(items, "She looked at Kasun")
    watched = at(items, "watched her go")
    note = at(items, "no idea")
    answer = {
        "about": "A first meeting is cut short.", "value": {"start": "joy", "end": "dread"}, "tone": "warm, uneasy",
        "units": [
            {"from_block": 0, "to_block": call, "wants": [{"character": "Anudi", "verb": "to charm"},
                                                           {"character": "Nobody", "verb": "to vanish"}],
             "turn_block": call},
            {"from_block": call - 3, "to_block": call + 1, "wants": [], "turn_block": None},  # overlaps: dropped
            {"from_block": call + 1, "to_block": len(items) - 1, "wants": [], "turn_block": 99},  # turn outside: None
            {"from_block": 5, "to_block": 2, "wants": [], "turn_block": None},  # backwards: dropped
        ],
        "subtext": [{"block": note, "who": "Kasun", "behaviour": "watches her go, still smiling",
                     "narration_only": False, "reason": ""},
                    {"block": 0, "who": "Ghost", "behaviour": "haunts", "narration_only": False, "reason": ""},
                    {"block": 1, "who": "", "behaviour": "", "narration_only": True, "reason": ""}],
        "breath": [
            {"after_block": call, "kind": "reaction", "who": "Anudi", "seconds": 2, "priority": 1, "why": "the call"},
            {"after_block": call, "kind": "atmosphere", "who": "", "seconds": 2, "priority": 2, "why": "same block"},
            {"after_block": look, "kind": "reaction", "who": "Ghost", "seconds": 2, "priority": 1, "why": "absent"},
            {"after_block": look, "kind": "reaction", "who": "Anudi", "seconds": 9, "priority": 1, "why": "too long"},
            {"after_block": look, "kind": "reaction", "who": "Anudi", "seconds": 2, "priority": 4, "why": "no such"},
            {"after_block": look, "kind": "reaction", "who": "Anudi", "seconds": 2, "priority": 1, "why": ""},
            {"after_block": 1, "kind": "atmosphere", "who": "", "seconds": 2, "priority": 3, "why": "nothing earns it"},
            {"after_block": watched, "kind": "button", "who": "Kasun", "seconds": 2, "priority": 1,
             "why": "last image"},
            {"after_block": call - 1, "kind": "button", "who": "Anudi", "seconds": 2, "priority": 1, "why": "second"},
            {"after_block": 999, "kind": "reaction", "who": "Anudi", "seconds": 2, "priority": 1, "why": "gone"},
        ],
        "ending": "Kasun, alone with the pot.",
    }
    r = reading.validate(answer, items, CAST, version=3, by="model")
    assert r.about and r.value.start == "joy" and r.value.end == "dread" and r.by == "model" and r.for_version == 3
    assert [(u.from_block, u.to_block) for u in r.units] == [(0, call), (call + 1, len(items) - 1)]
    assert r.units[0].wants == {"Anudi": "to charm"} and r.units[0].turn_block == call
    assert r.units[1].turn_block is None
    assert [(b.after_block, b.kind) for b in r.breath] == [(call, "reaction"), (watched, "button")]
    assert [(t.block, t.narration_only) for t in r.subtext] == [(note, False)]
    assert r.subtext[0].behaviour.startswith("watches her go")


def test_every_story_note_has_behaviour_or_a_reason():
    items = scene2_items()
    r = reading.validate({"about": "x", "units": [], "subtext": [], "breath": []}, items, CAST, version=1, by="model")
    assert [(t.block, t.narration_only, bool(t.reason)) for t in r.subtext] == [(at(items, "no idea"), True, True)]


def test_breath_must_be_earned_by_a_turn_a_unit_or_subtext():
    items = scene2_items()
    note = at(items, "no idea")
    cold = {"after_block": 1, "kind": "atmosphere", "who": "", "seconds": 1.5, "priority": 3, "why": "mood"}
    assert reading.validate({"about": "x", "breath": [cold]}, items, CAST, version=1, by="model").breath == []
    unit = {"from_block": 0, "to_block": 1, "wants": [], "turn_block": None}  # block 1 ends a unit: earned
    assert len(reading.validate({"about": "x", "units": [unit], "breath": [cold]}, items, CAST, version=1,
                                by="model").breath) == 1
    sub = {"block": note, "who": "Kasun", "behaviour": "watches", "narration_only": False, "reason": ""}
    late = {**cold, "after_block": note}
    assert len(reading.validate({"about": "x", "subtext": [sub], "breath": [late]}, items, CAST, version=1,
                                by="model").breath) == 1


def test_a_reading_is_stale_when_the_script_moves_but_its_breath_follows_its_block():
    items = scene2_items()
    r = reading.by_rules(items, CAST, version=1)
    assert not r.stale(items, 1) and r.stale(items, 2)  # a new script version
    call = at(items, "Anudi, where are you")
    # a person adds a block at the top: every number moves, the stored breath still finds its block by identity
    shifted = [replace(i, index=i.index + 1) for i in items]
    shifted.insert(0, act(0, "A bell rings in the distance."))
    assert r.stale(shifted, 1)
    held = {i.index for i in reading.apply(shifted, r) if i.hold_s > 0}
    assert call + 1 in held and call not in held
    # a block that is gone takes its breath with it
    gone = [i for i in items if i.index != call]
    gone = [replace(i, index=n) for n, i in enumerate(gone)]
    assert len([i for i in reading.apply(gone, r) if i.hold_s > 0]) == len([b for b in r.breath]) - 1


def test_apply_puts_the_readings_time_on_the_blocks_and_a_turn_look_counts_as_an_act():
    items = scene2_items()
    r = reading.by_rules(items, CAST, version=1)
    timed = reading.apply(items, r)
    call, look = at(timed, "Anudi, where are you"), at(timed, "She looked at Kasun")
    assert items[look].screen == "with_line" and items[look].picture_s == 0.5
    assert timed[look].screen == "act" and timed[look].picture_s == 1.5 and timed[look].turn
    assert timed[call].hold_s == 1.5 and timed[call].hold_kind == "reaction" and timed[call].hold_who == "Anudi"
    assert timed[call].turn and timed[call].hold_priority == 1
    assert reading.apply(items, None) == items  # no reading: nothing changes
    off = r.model_copy(update={"breath": [b.model_copy(update={"off": True}) for b in r.breath]})
    assert not any(i.hold_s for i in reading.apply(items, off))


def test_optional_breath_goes_first_and_priority_one_is_never_offered():
    items = scene2_items()
    items[1] = replace(items[1], hold_s=1.0, hold_kind="atmosphere", hold_priority=3)
    items[4] = replace(items[4], hold_s=1.0, hold_kind="transition", hold_priority=2)
    items[6] = replace(items[6], hold_s=1.5, hold_kind="reaction", hold_priority=1)
    assert [i.index for i in reading.optional_breath(items)] == [1, 4]
    assert reading.release(items, 1)[1].hold_s == 0.0 and reading.release(items, 1)[4].hold_s == 1.0


def test_the_envelope_marks_and_a_new_split_clears_but_a_persons_switch_stays():
    items = scene2_items()
    r = reading.by_rules(items, CAST, version=1)
    call = at(items, "Anudi, where are you")
    marked = reading.mark_off(r, reading.apply(items, r), [call])
    assert [b.off_by for b in marked.breath if b.off] == ["envelope"] and marked.by == "rules"
    person = marked.model_copy(update={"breath": [marked.breath[0].model_copy(update={"off": True, "off_by": "person"}),
                                                  *marked.breath[1:]]})
    cleared = reading.clear_envelope(person)
    assert cleared.breath[0].off is True and not any(b.off for b in cleared.breath[1:])


# ── Phase 2: the kernel gives feeling time ─────────────────────────────────────────────────


def test_a_scene_with_no_reading_times_exactly_as_before():
    items = scene2_items()
    slots, need = shot_clock(items)
    assert reading.apply(items, None) == items
    assert need == shot_clock(reading.apply(items, None))[1] and slots
    plain = [say(0, "A", 6), say(1, "B", 6)]
    # lead-in, line, gap, line, tail: exactly the old arithmetic
    assert shot_clock(plain)[1] == LEAD_IN_S + line_seconds(plain[0]) + LINE_GAP_S + line_seconds(plain[1]) + TAIL_S


def test_a_hold_after_the_last_line_replaces_the_tail():
    one = [say(0, "A", 6, hold_s=1.5, hold_kind="reaction")]
    assert shot_clock(one)[1] == LEAD_IN_S + line_seconds(one[0]) + 1.5
    assert shot_clock([say(0, "A", 6)])[1] == LEAD_IN_S + line_seconds(one[0]) + TAIL_S


def test_a_hold_after_an_action_is_a_pause_before_the_next_thing():
    shot = [act(0, hold_s=2.0, hold_kind="reaction"), say(1, "A", 4)]
    slots, need = shot_clock(shot)
    assert slots[0].end_s == 1.5 and slots[1].start_s == 3.5  # 1.5 s of picture, 2 s held, then the line
    assert need == 3.5 + line_seconds(shot[1]) + TAIL_S
    ends_on_it = [say(0, "A", 4), act(1, hold_s=2.0, hold_kind="button")]
    assert shot_clock(ends_on_it)[1] == shot_clock([say(0, "A", 4), act(1)])[1] + 2.0 - 0.0


def test_the_answer_to_a_turn_waits_longer_than_an_ordinary_reply():
    ordinary = [say(0, "A"), say(1, "B")]
    turn = [say(0, "A", turn=True), say(1, "B")]
    gap = shot_clock(turn)[0][1].start_s - shot_clock(turn)[0][0].end_s
    base = shot_clock(ordinary)[0][1].start_s - shot_clock(ordinary)[0][0].end_s
    assert round(base, 2) == LINE_GAP_S and round(gap, 2) == TURN_GAP_S
    held = [say(0, "A", turn=True, hold_s=2.0), say(1, "B")]
    assert round(shot_clock(held)[0][1].start_s - shot_clock(held)[0][0].end_s, 2) == 2.0  # the longer of the two


def test_a_turn_look_takes_an_acts_time_not_half_a_second():
    items = scene2_items()
    r = reading.by_rules(items, CAST, version=1)
    look = at(items, "She looked at Kasun")
    timed = reading.apply(items, r)
    gained = sum(i.picture_s for i in timed) - sum(i.picture_s for i in items)
    assert gained == 2.0  # 0.5 -> 1.5 for the laugh and for the look
    assert items[look].picture_s == 0.5 and timed[look].picture_s == 1.5


def test_holds_are_reported_on_the_shot_that_has_their_block():
    items = scene2_items()
    r = reading.by_rules(items, CAST, version=1)
    timed = reading.apply(items, r)
    call = at(timed, "Anudi, where are you")
    result = fit(timed, [ProposedShot(0, call + 1), ProposedShot(call + 1, len(timed))], envelope_s=60)
    assert any((call, 1.5, "reaction") in s.holds for s in result.shots)
    assert result.breath_s == sum(b.seconds for b in r.breath)
    assert fit(items, [ProposedShot(0, len(items))], envelope_s=60).breath_s == 0


def test_a_hold_adds_to_the_shots_need_and_can_crowd_a_locked_shot():
    items = [say(0, "A", 12, hold_s=3.0, hold_kind="reaction")]
    r = fit(items, [ProposedShot(0, 1, duration=4, duration_locked=True)], envelope_s=10)
    assert r.crowded == [1] and r.shots[0].need_s > 4


def test_the_timeline_text_shows_the_hold():
    items = [act(0, "She stares.", hold_s=2.0, hold_kind="reaction"), say(1, "A", 4)]
    from contracts.shotplan import timeline_text
    assert "[then hold 2.0 s, reaction]" in timeline_text(items)


def test_scene_items_read_the_scenes_stored_reading_and_item_rows_keep_it():
    items = scene2_items()
    r = reading.by_rules(items, CAST, version=1)
    script = bridges.with_bridges(scene2.blocks(screens=True), scene2.lines(), 1, CAST)
    scene = {"script": script, "reading": r.model_dump(mode="json")}
    timed = sceneplan.scene_items(scene, scene2.lines())
    assert sum(1 for i in timed if i.hold_s) == len(r.breath) and any(i.turn for i in timed)
    back = [sceneplan.item_of(n, sceneplan.item_row(i)) for n, i in enumerate(timed)]
    assert back == timed  # the director's working copy keeps feeling's time
    assert sceneplan.scene_items({"script": script}, scene2.lines()) == items  # no reading
    assert all("hold_s" not in b for b in sceneplan.script_rows([sceneplan.item_row(i) for i in timed]))


def test_the_fit_report_says_how_much_breath_the_scene_holds():
    items = reading.apply(scene2_items(), reading.by_rules(scene2_items(), CAST, version=1))
    result = fit(items, [ProposedShot(0, len(items))], envelope_s=60)
    assert sceneplan.fit_report(result, "rules")["breath"] == {"kept_s": round(result.breath_s, 2)}
    assert "breath" not in sceneplan.fit_report(fit(scene2_items(), [ProposedShot(0, 21)], envelope_s=60), "rules")
