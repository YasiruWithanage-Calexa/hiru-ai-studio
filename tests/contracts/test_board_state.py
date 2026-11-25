"""plan/2026-11-23c: the Scene board writer reads the whole opening state, props are white clay stand-ins, code checks
the writer's hands, and pins carry a version. Pure: rows in, words out, no model.

The scene is shaped like the board of 2026-11-23 (scene de75bc31): Kasun hands Anudi her phone on a wet pavement; her
scene condition says "Holding the open umbrella" though no shot's plan has one."""
from __future__ import annotations

from typing import Any

from contracts import board as kit
from contracts.props import PROPS_SLOT, RosterProp

KASUN, ANUDI = "c-kasun", "c-anudi"
NAMES = {KASUN: "Kasun", ANUDI: "Anudi"}


def scene(**over: Any) -> dict[str, Any]:
    return {
        "heading": "EXT. ROADSIDE - DAY", "script": [{"text": "Anudi takes her phone from Kasun."}, {"text": ""},
                                                     {"text": "Her phone rings."}, {"text": "She walks away."}],
        "staging": {"by": "stager", "basis": "", "zones": ["roadside", "food business"],
                    "marks": [{"block": 0, "who": "Anudi", "zone": "roadside", "facing": "left", "frame_side": "right",
                               "posture": "standing", "holding": "", "left_hand": "", "right_hand": ""},
                              {"block": 0, "who": "Kasun", "zone": "roadside", "facing": "right",
                               "frame_side": "left", "posture": "standing", "holding": "phone",
                               "right_hand": "phone"},
                              {"block": 1, "who": "Anudi", "zone": "roadside", "holding": "phone",
                               "right_hand": "phone"},
                              {"block": 1, "who": "Kasun", "zone": "roadside", "holding": ""},
                              {"block": 3, "who": "Anudi", "zone": "off", "posture": "walking", "holding": "phone"}],
                    "props": [{"block": 0, "prop": "tiffin box", "where": "on the counter", "state": "closed"}]},
        "raphael": {"mood": ["warm"],
                    "edit": {"treatment": {"geography": "The pavement runs across the frame; the stall at screen "
                                                        "left, the wall at right. " + "x" * 320,
                                           "colour_script": [{"sequence": "A", "palette": "grey", "light": "overcast",
                                                              "grade": "muted"}],
                                           "key_image": "The phone between two hands."}},
                    "clips": [{"slate": "4A-1", "blocks": [0], "summary": "Kasun returns the phone.", "over": "",
                               "angle": "eye level"}],
                    "breakdown": {"shots": [{"n": 1, "blocks": [0, 1], "blocking": "Kasun left, Anudi right",
                                             "props": "the phone in Kasun's right hand", "performance": "",
                                             "light": "overcast", "must_read": "the phone"}]}},
        "coverage": {"axis": "The pavement runs across the frame"},
        **over,
    }


def shot(number: int = 1, start: int = 0, end: int = 1, **over: Any) -> dict[str, Any]:
    return {"id": f"s{number}", "number": number, "slate": "4A-1", "framing": "TWO", "block_start": start,
            "block_end": end,
            "ir": {"setting": "A wet roadside.", "lighting": "overcast",
                   "first_frame": {"composition": "Kasun left, Anudi right.",
                                   "subjects": ["Kasun extends the handset in his right hand."]},
                   "subjects": [{"id": "C01", "action": "Gives the phone.", "position": "frame left"}],
                   "beats": [{"action": "The handset passes from his right hand into hers.",
                              "performance": "Both watch the handset.", "camera": "Locked off.",
                              "director_line": "x"}]},
            "intent": {"story": "She gets her phone back.", "on_screen": [KASUN, ANUDI], "heard_only": [],
                       "opens": "Kasun: standing, phone in right hand"},
            **over}


def board_shots(rows: list[dict[str, Any]], sc: dict[str, Any] | None = None) -> list[kit.BoardShot]:
    return kit.board_shots(sc or scene(), rows, [], {r["id"]: ["Kasun", "Anudi"] for r in rows}, [], NAMES)


# ── §3.1 what the writer reads ─────────────────────────────────────────────────────────────────────────────────


def test_a_shot_plan_carries_the_opening_state_marks_hands_props_and_breakdown():
    plan = board_shots([shot()])[0].plan
    assert plan["opening_state"] == "Kasun: standing, phone in right hand"
    assert plan["beats"] == [{"action": "The handset passes from his right hand into hers.",
                              "performance": "Both watch the handset.", "camera": "Locked off."}]
    marks = {m["who"]: m for m in plan["marks"]}
    assert marks["Kasun"]["right_hand"] == "phone" and marks["Anudi"]["facing"] == "left", "every stager field"
    assert marks["Anudi"]["frame_side"] == "right"
    assert plan["props_down"] == [{"prop": "tiffin box", "where": "on the counter", "state": "closed"}]
    assert plan["clip"] == {"summary": "Kasun returns the phone.", "angle": "eye level"}
    assert plan["breakdown"]["props"] == "the phone in Kasun's right hand"
    assert "phone" in plan["hands"].lower(), "the same holding words a frame gets"


def test_marks_are_read_by_block_even_when_the_map_has_no_basis():
    """The board of 2026-11-23: `basis` was "" so the ledger placed nothing and `opens` was never written."""
    later = kit.marks_at(scene()["staging"]["marks"], 1, ["Anudi"])
    assert later == [{"who": "Anudi", "zone": "roadside", "holding": "phone", "right_hand": "phone"}]


def test_someone_only_heard_is_named_for_the_writer():
    row = shot(intent={"story": "", "on_screen": [ANUDI], "heard_only": [KASUN]})
    assert board_shots([row])[0].plan["heard_only"] == ["Kasun"]


def test_the_bundle_gives_the_whole_geography_colour_script_and_every_mark_field():
    bundle = kit.writer_bundle(scene(), board_shots([shot()]), [], {"name": "Roadside"}, [], [])
    sc = bundle["scene"]
    assert len(sc["geography"]) > 300 and "axis" not in sc, "no longer cut to 300 letters as the axis"
    assert sc["colour_script"] == [{"palette": "grey", "light": "overcast", "grade": "muted"}]
    assert sc["key_image"] and sc["zones"] == ["roadside", "food business"]
    assert {"facing", "frame_side", "right_hand"} <= set(sc["staging"][1])
    assert sc["props_set_down"][0]["where"] == "on the counter"


def test_a_scene_without_a_treatment_keeps_its_axis():
    bundle = kit.writer_bundle(scene(raphael={}), board_shots([shot()], scene(raphael={})), [], {}, [], [])
    assert bundle["scene"]["axis"] == "The pavement runs across the frame"


# ── the writer's answer ────────────────────────────────────────────────────────────────────────────────────────


def answer(**panel: Any) -> dict[str, Any]:
    p = {"shot": 1, "zone": "roadside", "camera": "Waist-up two-shot.", "background": "The stall at left.",
         "picture": "The red mannequin holds out the clay phone.",
         "people": [{"name": "Kasun", "state": "", "left_hand": "empty, at his side", "right_hand": "the clay phone"},
                    {"name": "Anudi", "state": "", "left_hand": "empty", "right_hand": "open palm under the phone"}],
         "props": [{"name": "phone", "held_by": "Kasun", "hand": "right", "rests_on": "", "frame_side": "centre"}]}
    p.update(panel)
    return {"world": "Overcast morning.", "geography": "Across.", "panels": [p], "conflicts": []}


def test_hands_and_props_survive_a_round_trip_and_an_old_board_still_loads():
    w = kit.Writer.of(answer())
    again = kit.Writer.of(w.dump())
    assert again == w and again.panels[0].people[0].right_hand == "the clay phone"
    assert again.panels[0].props[0] == kit.PanelProp(name="phone", held_by="Kasun", hand="right",
                                                     frame_side="centre")
    old = {"world": "w", "geography": "g", "panels": [{"shot": 1, "zone": "z", "camera": "c", "background": "b",
                                                       "picture": "p", "people": [{"name": "Kasun", "state": ""}]}]}
    assert kit.Writer.of(old).dump()["panels"][0] == {**old["panels"][0]}, "a board from before is stored as it was"


def test_renumber_and_a_one_panel_answer_keep_hands_and_props():
    w = kit.Writer.of(answer())
    _, moved = kit.renumber([{"shot_id": "s1", "number": 1}], w, [{"id": "s1", "number": 4}])
    assert moved.panels[0].shot == 4 and moved.panels[0].props == w.panels[0].props
    one = kit.panel_answer(answer(), 7)
    assert one is not None and one.shot == 7 and one.people[0].right_hand == "the clay phone"


# ── §3.3 the image prompt ──────────────────────────────────────────────────────────────────────────────────────


def test_the_board_prompt_paints_props_as_white_clay_and_spells_out_the_hands():
    w = kit.Writer.of(answer())
    prompt = kit.board_prompt(w, [1], ["the location plate for Roadside"], {"Kasun": "red", "Anudi": "blue"},
                              kit.TALL, props=["phone"])
    assert "white clay stand-in" in prompt and "(phone)" in prompt
    assert "Hands: the red mannequin: left hand empty, at his side; right hand the clay phone." in prompt
    assert kit.SUPPORT in prompt and "exactly two arms and two hands" in prompt
    assert "Everything else (the place, the props" not in prompt, "props are no longer painted for real"
    assert "white" in kit.prop_line([]) and "grey" not in kit.prop_line([]), "grey is a background person"


def test_a_panel_painted_again_is_told_what_was_wrong():
    w = kit.Writer.of(answer())
    fix = kit.fix_line(["blue: a third arm carries the bag"])
    prompt = kit.panel_prompt(w, w.panels[0], [], {"Kasun": "red"}, fix=fix)
    assert "A first painting of this panel was wrong: blue: a third arm carries the bag." in prompt
    assert kit.fix_line([]) == ""


# ── §3.4 the free check ────────────────────────────────────────────────────────────────────────────────────────


def test_what_a_person_carries_through_the_scene_may_be_in_a_hand():
    """2026-11-23 (reversing Q6): scenes 2 and 3 give Anudi an open umbrella and a handbag; scene 4's plan only has
    the phone. Her scene condition carries the umbrella on, so it is no conflict; a thing nothing gives is."""
    w = kit.Writer.of(answer(people=[{"name": "Anudi", "state": "", "left_hand": "the clay umbrella's handle",
                                      "right_hand": "the clay phone"}]))
    carried = {"Anudi": "Holding the open umbrella; shoe toes remain lightly damp. A tan handbag."}
    assert kit.writer_findings(w, board_shots([shot()]), carried) == []
    found = kit.writer_findings(w, board_shots([shot()]))
    assert any("Anudi holds the umbrella, which neither the plan" in f for f in found)
    assert not any("holds the phone" in f for f in found), "the plan gives the phone"


def test_only_a_clay_thing_is_read_as_held():
    """2026-11-23: "grips the clay phone around its lower edges" came out as a held "edges"."""
    assert kit._held("Grips the clay phone around its lower edges, near side.") == "phone"
    assert kit._held("Holds the clay phone broad-plane-up at chest height.") == "phone"
    assert kit._held("Empty, extended toward centre beneath Anudi's hand.") == ""
    assert kit._held("The clay umbrella's shaft in her fist") == "umbrella"


def test_the_places_stay_real():
    """2026-11-23: the food three-wheeler, a canon place, was painted as a white clay van."""
    line = kit.prop_line(["phone", "umbrella"], ["Colombo roadside", "Food three-wheeler"])
    assert "(phone, umbrella)" in line and "and Colombo roadside, Food three-wheeler, painted as a real" in line


def test_three_things_in_two_hands_a_floating_prop_and_someone_only_heard_are_reported():
    w = kit.Writer.of(answer(
        people=[{"name": "Anudi", "state": "", "left_hand": "the clay umbrella", "right_hand": "the clay phone"},
                {"name": "Kasun", "state": ""}],
        props=[{"name": "bag", "held_by": "Anudi", "hand": "left"}, {"name": "kettle"}]))
    rows = [shot(intent={"story": "umbrella bag phone", "on_screen": [ANUDI], "heard_only": [KASUN]})]
    found = " | ".join(kit.writer_findings(w, board_shots(rows)))
    assert "Anudi is given 3 things to hold" in found
    assert "the kettle is neither held nor resting" in found
    assert "Kasun is only heard in this shot" in found


# ── first frame: the props come back ───────────────────────────────────────────────────────────────────────────


def test_a_frame_from_the_panel_turns_the_clay_back_into_the_props():
    assert kit.unprop("Anudi holds the clay phone; a white clay stand-in of the umbrella leans on the wall.") == (
        "Anudi holds the phone; the umbrella leans on the wall.")
    w = kit.Writer.of(answer())
    sections = kit.frame_sections(w, 1, {"Kasun": "red"}, [], ())
    # plan/2026-11-25b: a panel that lists its props leaves the slot for the bound paragraph; with nothing bound the
    # frame keeps today's stand-in rule
    assert PROPS_SLOT in sections and kit.PROP_STAND_INS not in sections and "clay" not in sections[-1]
    assert kit.PROP_STAND_INS in kit.fill_props(sections, "", blocking=False)
    assert "bound words" in kit.fill_props(sections, "bound words", blocking=False)
    old = kit.Writer.of(answer(props=[], picture="Kasun holds the clay phone out."))
    assert kit.PROP_STAND_INS in kit.frame_sections(old, 1, {"Kasun": "red"}, [], ()), "a board before 23c"


def test_a_name_that_is_none_of_the_scenes_props_is_reported_not_a_fault():
    """plan/2026-11-25b: a stand-in the roster does not know is painted from words only in the frame; the panel is
    still attached (no `_FAULT_MARKS` word)."""
    roster = [RosterProp(key="p", name="phone"), RosterProp(key="h", name="handbag")]
    w = kit.Writer.of(answer(props=[{"name": "phone", "held_by": "Kasun", "hand": "right"},
                                    {"name": "bag", "held_by": "Anudi", "rests_on": "her left forearm"},
                                    {"name": "kettle", "rests_on": "the counter"}]))
    found = kit.writer_findings(w, board_shots([shot()]), roster=roster)
    assert found == ["Shot 1: the kettle is not one of the scene's props; its first frame paints it from words only."]
    assert not kit.panel_faults(kit.Writer.of({**answer(), "conflicts": found}), 1)
    assert kit.writer_findings(w, board_shots([shot()])) == [], "no roster, no line (as before)"


def test_the_boards_hands_are_the_frames_one_hands_sentence():
    w = kit.Writer.of(answer())
    held = kit.board_hands(kit.frame_sections(w, 1, {"Kasun": "red"}, [], ()))
    assert held.startswith(kit.HELD_HEAD) and "Kasun: left hand empty" in held
    assert kit.board_hands(["The scene: rain."]) == ""


# ── D7 pins ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_cell_pinned_before_stays_current_and_a_new_pin_sees_the_opening_state():
    row = shot()
    old = kit.legacy_pin(row)
    assert ":" not in old and kit.pin_matches(old, row), "a board painted before keeps its pin"
    assert kit.plan_pin(row).startswith("v3:") and kit.pin_matches(kit.plan_pin(row), row)
    moved = shot(intent={**row["intent"], "opens": "Kasun: standing, empty hands"})
    assert kit.pin_matches(old, moved), "the old pin never read the opening state"
    assert not kit.pin_matches(kit.plan_pin(row), moved), "the new one does"
    stale = kit.stale_cells([{"shot_id": "s1", "number": 1, "pin": old}], [row])
    assert not stale.any


def test_a_v2_pin_stays_current_and_a_v3_pin_sees_the_camera_agents_camera():
    """plan/2026-11-23d §2.2: the board paints the Camera agent's camera; a camera change marks the panel."""
    designed = shot(design={"camera": {"state": "designed", "opens_on": "Anudi chest up"},
                            "recommended": {"angle": "high", "height": "above_head", "lens": "65mm"}})
    v2 = f"v2:{kit._pin_hash(designed, kit._PIN_INTENT_V2)}"
    assert kit.pin_matches(v2, designed), "a board pinned in v2 stays current"
    assert board_shots([designed])[0].plan["camera_design"] == {
        "angle": "high", "height": "above_head", "lens": "65mm", "opens_on": "Anudi chest up"}
    moved = {**designed, "camera_overrides": {"angle": "eye_level"}}
    assert kit.pin_matches(v2, moved), "v2 never read the camera"
    assert not kit.pin_matches(kit.plan_pin(designed), moved), "v3 does"
    assert kit.camera_of(shot()) == {}, "no Camera agent design: the planner's cinematography is the camera"
