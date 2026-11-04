"""The staging map (plan/2026-11-01d, Phase 4): who is where, and the free checks on it."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from contracts import bridges, reading, sceneplan, stagemap
from contracts.shotplan import Item, ProposedShot, fit

CAST = ["Anudi", "Kasun"]


def say(index: int, who: str, delivery: str = "", **extra: Any) -> Item:
    return Item(index, "dialogue", "word word word word", who, who.casefold(), delivery, f"l{index}", **extra)


def act(index: int, text: str, screen: str = "act", **extra: Any) -> Item:
    return Item(index, "action", text, screen=screen, **extra)


def scene() -> list[Item]:
    return [act(0, "Kasun stirs the pot at the stall."), say(1, "Anudi"), say(2, "Kasun"), act(3, "Anudi laughs."),
            say(4, "Anudi"), say(5, "Kasun")]


def mark(block: int, who: str, zone: str, **extra: Any) -> dict[str, Any]:
    return {"block": block, "who": who, "zone": zone, "facing": "", "frame_side": "", "holding": "", **extra}


def staged(items: list[Item], marks: list[dict[str, Any]], zones: tuple[str, ...] = ("stall", "gate", "bench"),
           ) -> stagemap.SceneStaging:
    return stagemap.validate({"zones": list(zones), "marks": marks}, items, CAST, version=1, by="model")


# ── validation: an invalid entry is dropped, not repaired ─────────────────────────────────────


def test_a_mark_is_kept_only_when_it_is_true_to_the_scene():
    items = scene()
    s = staged(items, [
        mark(0, "Kasun", "stall"), mark(1, "Anudi", "Stall", facing="right", frame_side="left"),
        mark(2, "Kasun", "moon"),  # not one of the spots
        mark(9, "Kasun", "stall"),  # no such block
        mark(3, "Farmer", "gate"),  # nobody of that name is in the scene
        mark(4, "Anudi", "gate", facing="up"),  # not a direction
        mark(5, "Kasun", "off"),  # leaving is allowed
    ])
    assert [(m.block, m.who, m.zone) for m in s.marks] == [(0, "Kasun", "stall"), (1, "Anudi", "stall"),
                                                           (5, "Kasun", "off")]
    assert s.marks[1].facing == "right" and s.by == "model" and s.basis == reading.basis(items)


def test_zones_are_two_to_six_names_and_never_off():
    items = scene()
    many = stagemap.validate({"zones": ["a", "b", "OFF", "c", "d", "e", "f", "g", "A"],
                              "marks": [mark(0, "Kasun", "a")]}, items, CAST, version=1, by="model")
    assert many.zones == ["a", "b", "c", "d", "e", "f"]
    one = stagemap.validate({"zones": ["a"], "marks": [mark(0, "Kasun", "a")]}, items, CAST, version=1, by="model")
    assert one.zones == [] and one.marks == []  # one spot is no map


def test_a_person_has_one_mark_per_block_and_a_mark_holds_until_the_next():
    items = scene()
    s = staged(items, [mark(0, "Kasun", "stall"), mark(0, "Kasun", "gate"), mark(4, "Kasun", "bench")])
    assert [m.zone for m in s.marks] == ["stall", "bench"]
    assert s.mark_at(items, "kasun", 3).zone == "stall" and s.mark_at(items, "Kasun", 5).zone == "bench"
    assert s.mark_at(items, "Anudi", 5) is None


def test_people_with_no_mark_are_named_so_nothing_is_guessed_about_them():
    items = scene()
    s = staged(items, [mark(0, "Kasun", "stall")])
    assert stagemap.unplaced(s, items, CAST) == ["Anudi"]


# ── teleports ─────────────────────────────────────────────────────────────────────────────────


def test_a_person_who_changes_spot_with_nothing_to_show_the_way_teleports_and_gets_one_step():
    items = scene()
    s = staged(items, [mark(0, "Kasun", "stall"), mark(1, "Anudi", "stall"), mark(4, "Anudi", "gate")])
    found = stagemap.teleports(s, items, CAST)
    assert [(f.code, f.block, f.who, f.zone) for f in found] == [("teleport", 4, ("Anudi",), "gate")]
    assert stagemap.plan_moves(s, items, CAST) == [(4, "Anudi", "gate")]


def test_a_walk_the_script_already_writes_is_no_teleport():
    items = scene()
    items[3] = act(3, "Anudi walks to the gate.", screen="move")
    s = staged(items, [mark(1, "Anudi", "stall"), mark(4, "Anudi", "gate")])
    assert stagemap.teleports(s, items, CAST) == [] and stagemap.plan_moves(s, items, CAST) == []
    # "She walked away" names no one: it moves whoever the map moves
    items[3] = act(3, "She walked away.", screen="move")
    assert stagemap.teleports(s, items, CAST) == []
    # but a walk by someone else does not carry Anudi
    items[3] = act(3, "Kasun walks to the gate.", screen="move")
    assert len(stagemap.teleports(s, items, CAST)) == 1


def test_entrances_and_exits_are_not_teleports():
    items = scene()
    s = staged(items, [mark(0, "Anudi", "off"), mark(1, "Anudi", "stall"), mark(5, "Anudi", "off")])
    assert stagemap.teleports(s, items, CAST) == []


def test_a_step_a_person_removed_is_never_added_again():
    items = scene()
    s = staged(items, [mark(1, "Anudi", "stall"), mark(4, "Anudi", "gate")])
    items[4] = replace(items[4], skip=(bridges.move_kind("Anudi"),))
    assert stagemap.plan_moves(s, items, CAST) == []
    assert len(stagemap.teleports(s, items, CAST)) == 1  # still told: the person chose to leave it


def test_without_a_map_nothing_about_places_is_checked():
    items = scene()
    assert stagemap.teleports(None, items, CAST) == [] and stagemap.plan_moves(None, items, CAST) == []


# ── the step in the script ────────────────────────────────────────────────────────────────────


def script_and_lines(items: list[Item]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    script, lines = [], []
    for i in items:
        if i.is_line:
            lines.append({"id": i.line_id, "production_id": "p", "scene_id": "s", "ord": len(lines),
                          "speaker": i.speaker, "text": i.text, "delivery": "", "character_id": i.speaker_id})
            script.append({"kind": "dialogue", "text": "", "line_id": i.line_id})
        else:
            script.append({"kind": "action", "text": i.text, "line_id": None, "screen": i.screen, "events": 1,
                           "for_version": 1})
    return script, lines


def test_the_step_is_an_ordinary_removable_move_block_and_the_numbers_follow():
    items = scene()
    script, lines = script_and_lines(items)
    out, where = bridges.insert_moves(script, lines, [(4, "Anudi", "gate")], 1)
    assert [b["text"] for b in out].index("Anudi crosses to the gate.") == 4 and len(out) == 7
    step = out[4]
    assert (step["implied"], step["by"], step["screen"], step["bridge"]) == (True, "staging", "move", "move:anudi")
    assert where == [0, 1, 2, 3, 5, 6]  # block 4 is now 5
    placed = sceneplan.items_for(out, lines)
    assert placed[4].implied and placed[4].picture_s == 2.5  # a move takes 2.5 s on the clock


def test_two_steps_before_one_block_keep_their_order():
    items = scene()
    script, lines = script_and_lines(items)
    out, where = bridges.insert_moves(script, lines, [(4, "Anudi", "gate"), (4, "Kasun", "bench")], 1)
    assert [b["text"] for b in out[4:6]] == ["Anudi crosses to the gate.", "Kasun crosses to the bench."]
    assert where[4] == 6


def test_the_map_and_the_reading_are_carried_across_the_new_block():
    items = scene()
    script, lines = script_and_lines(items)
    s = staged(items, [mark(1, "Anudi", "stall"), mark(4, "Anudi", "gate")])
    r = reading.SceneReading(by="rules", for_version=1, basis=reading.basis(items),
                             units=[reading.Unit(from_block=0, to_block=2),
                                    reading.Unit(from_block=3, to_block=5, turn_block=4)],
                             breath=[reading.Breath(after_block=4, anchor=reading.block_key(items[4]),
                                                    kind="reaction", who="Anudi", seconds=1.5, priority=1,
                                                    why="turn")])
    out, where = bridges.insert_moves(script, lines, stagemap.plan_moves(s, items, CAST), 1)
    placed = sceneplan.items_for(out, lines)
    s2, r2 = stagemap.remap(s, placed, where), reading.remap(r, placed, where)
    assert not s2.stale(placed, 1) and r2.basis == reading.basis(placed)
    assert stagemap.teleports(s2, placed, CAST) == []  # the step now carries her
    assert (r2.units[1].from_block, r2.units[1].to_block, r2.units[1].turn_block) == (3, 6, 5)
    assert r2.resolved(placed)[0][1] == 5  # the hold is still after her line


def test_removing_a_move_is_remembered_on_the_block_after_it_and_survives_a_script_edit():
    items = scene()
    script, lines = script_and_lines(items)
    out, _ = bridges.insert_moves(script, lines, [(4, "Anudi", "gate")], 1)
    after = bridges.skip_bridge(out, 4)
    assert len(after) == 6 and after[4]["skip_bridges"] == ["move:anudi"]
    placed = sceneplan.items_for(after, lines)
    assert placed[4].skip == ("move:anudi",)
    # a person's script edit (the editor sends bare blocks) that drops the step is remembered the same way
    bare = [{"kind": b["kind"], "text": b["text"], "line_id": b["line_id"]} for b in out if not b.get("implied")]
    kept = bridges.carry(out, bare)
    assert kept[4]["skip_bridges"] == ["move:anudi"]
    # and a block the person left alone keeps what was remembered on it
    again = bridges.carry(after, [{"kind": b["kind"], "text": b["text"], "line_id": b["line_id"]} for b in after])
    assert again[4]["skip_bridges"] == ["move:anudi"]
    assert bridges.is_bridge("move:anudi") and bridges.is_bridge(bridges.ANSWER_PHONE) and not bridges.is_bridge("x")


# ── the cuts ──────────────────────────────────────────────────────────────────────────────────


def plan(items: list[Item], cuts: list[tuple[int, int, str]], link: str = "cut"):
    shots = [ProposedShot(a, b, framing, "", None, None, False, link) for a, b, framing in cuts]
    return fit(items, shots, envelope_s=60)


def test_a_cut_that_swaps_two_people_across_the_frame_crosses_the_line():
    items = scene()
    s = staged(items, [mark(0, "Kasun", "stall", frame_side="right"), mark(0, "Anudi", "stall", frame_side="left"),
                       mark(4, "Anudi", "stall", frame_side="right"), mark(4, "Kasun", "stall", frame_side="left")])
    result = plan(items, [(0, 4, "TWO"), (4, 6, "TWO")])
    found = stagemap.line_crossed(s, items, result, CAST)
    assert [(f.code, f.shot) for f in found] == [("line_crossed", 2)] and set(found[0].who) == {"kasun", "anudi"}
    # a deliberate re-angle says so with a match link
    assert stagemap.line_crossed(s, items, plan(items, [(0, 4, "TWO"), (4, 6, "TWO")], link="match"), CAST) == []
    # people who keep their sides are fine
    keep = staged(items, [mark(0, "Kasun", "stall", frame_side="right"), mark(0, "Anudi", "stall", frame_side="left")])
    assert stagemap.line_crossed(keep, items, result, CAST) == []


def test_two_singles_that_look_the_same_way_do_not_look_at_each_other():
    items = scene()
    result = plan(items, [(0, 2, "MCU"), (2, 3, "MCU"), (3, 6, "TWO")])
    bad = staged(items, [mark(1, "Anudi", "stall", facing="right"), mark(2, "Kasun", "stall", facing="right")])
    assert [f.code for f in stagemap.eyeline(bad, items, result)] == ["eyeline"]
    good = staged(items, [mark(1, "Anudi", "stall", facing="right"), mark(2, "Kasun", "stall", facing="left")])
    assert stagemap.eyeline(good, items, result) == []
    assert stagemap.eyeline(None, items, result) == []


def test_a_heard_voice_is_not_in_the_picture():
    phone = say(1, "Father", delivery="on the phone")
    assert stagemap.people_in([phone, act(2, "Anudi listens.")], ["Anudi", "Father"]) == ["anudi"]
