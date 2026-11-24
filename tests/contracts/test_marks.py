"""Fixed marks (plan/2026-11-24d phase 1, `contracts/marks.py`): stretches from the staging map, the board writer's
spots, the lab's words, the blocking plate's view, label, prompt and pin. Nothing is painted."""
from __future__ import annotations

from contracts import board as kit
from contracts import marks as mk
from contracts import reading as rd
from contracts.safe_depiction import blocking
from contracts.shotplan import Item


def items(n: int, **bridges: str) -> list[Item]:
    """n whole action blocks; `bridges`: "b3" → "move:anudi" makes block 3 an implied move."""
    return [Item(index=i, kind="action", text=f"block {i}", implied=f"b{i}" in bridges,
                 bridge=bridges.get(f"b{i}", "")) for i in range(n)]


def mark(block: int, who: str, zone: str, posture: str = "", **more: str) -> dict:
    return {"block": block, "who": who, "zone": zone, "posture": posture, **more}


def shot(sid: str, number: int, start: int, end: int) -> dict:
    return {"id": sid, "number": number, "block_start": start, "block_end": end}


BOTH = ["Kasun", "Anudi"]


def test_shots_label_reads_as_a_person_says_it():
    assert mk.shots_label([16]) == "shot 16"
    assert mk.shots_label([2, 1]) == "shots 1 and 2"
    assert mk.shots_label(range(1, 16)) == "shots 1 to 15"
    assert mk.shots_label([1, 2, 3, 4, 5, 7]) == "shots 1 to 5 and 7", "a cinematic clip can open out of order"
    assert mk.shots_label([1, 2, 5]) == "shots 1, 2 and 5"


def test_whole_index_maps_line_parts_to_the_maps_blocks():
    """Lab phase 0: a scene planned with line parts counts each part, the staging map counts whole blocks."""
    parts = [Item(index=0, kind="action"), Item(index=1, kind="dialogue", line_id="l", part=1, parts=3),
             Item(index=2, kind="dialogue", line_id="l", part=2, parts=3),
             Item(index=3, kind="dialogue", line_id="l", part=3, parts=3), Item(index=4, kind="action")]
    assert mk.whole_index(parts) == [0, 1, 1, 1, 2]


def test_no_map_means_no_stretches():
    assert mk.stretches(None, items(4), [shot("a", 1, 0, 2)]).stretches == ()
    assert mk.stretches({"marks": []}, items(4), [shot("a", 1, 0, 2)]).stretches == ()
    assert mk.panel_line(mk.Blocking(), "a") == ""


def test_a_still_scene_is_one_stretch_with_one_plate():
    """Scene 4: both stand from block 0; nobody moves until after the last shot."""
    staging = {"marks": [mark(0, "Anudi", "roadside", "standing"), mark(0, "Kasun", "roadside", "standing")]}
    shots = [shot("a", 1, 0, 2), shot("b", 2, 2, 4), shot("c", 3, 4, 6)]
    got = mk.stretches(staging, items(6), shots, seen={"a": BOTH, "b": ["Anudi"], "c": BOTH})
    (s,) = got.stretches
    assert s.n == 1 and s.label == "shots 1 to 3" and set(s.people) == set(BOTH) and s.plate
    assert mk.panel_line(got, "b") == ("Marks: on the ground marks of shots 1 to 3, the same gap as in every panel of "
                                       "them.")


def test_a_walk_ends_the_stretch_and_the_panels_say_who_leaves():
    """Block 3: Anudi starts walking (same zone); block 5: she stops at the gate. Kasun never moves."""
    staging = {"marks": [mark(0, "Kasun", "roadside", "standing"), mark(0, "Anudi", "roadside", "standing"),
                         mark(3, "Anudi", "roadside", "walking"), mark(5, "Anudi", "gate", "standing")]}
    shots = [shot("a", 1, 0, 2), shot("b", 2, 2, 4), shot("c", 3, 4, 5), shot("d", 4, 5, 6)]
    seen = {"a": BOTH, "b": BOTH, "c": BOTH, "d": BOTH}
    got = mk.stretches(staging, items(6), shots, seen=seen)
    one, two, three = got.stretches
    assert (one.numbers, two.numbers, three.numbers) == ((1, 2), (3,), (4,))
    assert two.travelling == ("Anudi",) and two.people == ("Kasun",) and two.left == ("Anudi",)
    assert three.left == ("Anudi",) and set(three.people) == set(BOTH)
    assert got.moves_in == {"b": ("Anudi",)}
    assert mk.panel_line(got, "b") == ("Marks: Kasun stays on the ground marks of shots 1 and 2; Anudi leaves that "
                                       "mark in this shot.")
    assert mk.panel_line(got, "c") == ("Marks: the ground marks of shot 3; Anudi no longer stands on the marks of "
                                       "shots 1 and 2.")
    assert mk.panel_line(got, "d") == "Marks: on the ground marks of shot 4."
    assert not two.plate and not three.plate, "one shot is its own truth: no plate"


def test_everyone_leaving_says_nobody_stands_on_the_old_marks():
    """Lab W: both leave the roadside at block 4; shot 3 is Kasun at his counter."""
    staging = {"marks": [mark(0, "Kasun", "roadside", "standing"), mark(0, "Anudi", "roadside", "standing"),
                         mark(4, "Kasun", "food business", "standing"), mark(4, "Anudi", "off")]}
    got = mk.stretches(staging, items(6), [shot("a", 1, 0, 2), shot("b", 2, 2, 4), shot("c", 3, 4, 6)],
                       seen={"a": BOTH, "b": BOTH, "c": ["Kasun"]})
    assert mk.panel_line(got, "c") == "Marks: the ground marks of shot 3; nobody stands on the marks of shots 1 and 2."
    assert got.stretches[1].people == ("Kasun",)


def test_sitting_down_on_the_spot_keeps_the_mark():
    """D1: a posture change alone is not a move."""
    staging = {"marks": [mark(0, "Anudi", "sofa", "standing"), mark(2, "Anudi", "sofa", "sitting")]}
    got = mk.stretches(staging, items(5), [shot("a", 1, 0, 2), shot("b", 2, 2, 5)], seen={"a": ["Anudi"],
                                                                                         "b": ["Anudi"]})
    assert len(got.stretches) == 1 and got.moves_in == {}


def test_an_entrance_an_exit_and_an_implied_move_each_start_a_stretch():
    staging = {"marks": [mark(0, "Kasun", "desk", "sitting"), mark(2, "Father", "entrance", "standing"),
                         mark(6, "Father", "off")]}
    got = mk.stretches(staging, items(8, b4="move:kasun"), [shot(str(i), i + 1, i, i + 1) for i in range(8)])
    assert [s.start for s in got.stretches] == [0, 2, 4, 6]
    assert got.stretches[2].left == ("Kasun",), "the bridge's lower-case name is the map's person"
    assert got.stretches[3].people == ("Kasun",), "an exit takes the person off the plate"


def test_a_shot_belongs_to_the_stretch_of_its_opening_block_through_line_parts():
    """Shot blocks count line parts; the map counts whole blocks (lab phase 0, scene 4's blocks 19-22)."""
    staging = {"marks": [mark(0, "Anudi", "roadside", "standing"), mark(3, "Anudi", "off", "walking")]}
    to_whole = [0, 1, 1, 1, 2, 3, 3]  # 7 part items over 4 whole blocks
    got = mk.stretches(staging, items(4), [shot("a", 1, 0, 4), shot("b", 2, 4, 5), shot("c", 3, 5, 7)],
                       to_whole=to_whole)
    assert got.of_shot == {"a": 1, "b": 1, "c": 2}


def test_a_map_written_for_another_script_is_read_through_its_anchors():
    blocks = items(6)
    staging = {"basis": "an-older-script",
               "marks": [mark(0, "Anudi", "roadside", "standing", anchor=rd.block_key(blocks[0])),
                         mark(9, "Anudi", "gate", "standing", anchor=rd.block_key(blocks[4])),
                         mark(7, "Kasun", "roadside", "standing", anchor="gone")]}
    got = mk.stretches(staging, blocks, [shot("a", 1, 0, 4), shot("b", 2, 4, 6)])
    assert [s.start for s in got.stretches] == [0, 4] and got.stretches[0].people == ("Anudi",)


def test_shown_counts_painted_shots_with_a_still_person():
    staging = {"marks": [mark(0, "Anudi", "roadside", "standing")]}
    shots = [shot("a", 1, 0, 1), shot("b", 2, 1, 2), shot("c", 3, 2, 3)]
    got = mk.stretches(staging, items(3), shots, seen={"a": ["Anudi"], "b": ["anudi"], "c": []}, painted=["a", "c"])
    assert got.stretches[0].shown == 1 and not got.stretches[0].plate


# ── the writer's spots and the words ─────────────────────────────────────────────────────────────────────────


def scene4() -> mk.Blocking:
    staging = {"marks": [mark(0, "Kasun", "roadside", "standing"), mark(0, "Anudi", "roadside", "standing")]}
    return mk.stretches(staging, items(20), [shot(f"s{i}", i, i, i + 1) for i in range(1, 16)],
                        seen={f"s{i}": BOTH for i in range(1, 16)})


SPOTS = [
    {"stretch": 1, "who": "kasun", "spot": "on the concrete pavement half a metre in from the kerb drain, one step to "
     "the right of the rear of the food three-wheeler, whose open service hatch and the blue awning above it are "
     "directly behind him and to his left"},
    {"stretch": 1, "who": "Anudi", "spot": "on the same pavement, the same half metre in from the drain",
     "apart": "about 1.2 metres to Kasun's right, in front of the green building, with the pale boundary wall "
              "beginning just to her right"},
]


def test_check_keeps_one_spot_per_person_and_reports_who_has_none():
    b = scene4()
    kept, problems = mk.check([*SPOTS, {"stretch": 1, "who": "Kasun", "spot": "elsewhere"},
                               {"stretch": 2, "who": "Kasun", "spot": "x"}, {"stretch": 1, "who": "Nimal", "spot": "x"},
                               {"stretch": 1, "who": "Anudi"}], b)
    assert [m.who for m in kept] == ["Kasun", "Anudi"] and "elsewhere" not in kept[0].spot and not problems
    kept, problems = mk.check(SPOTS[:1], b)
    assert problems == ["Shots 1 to 15: the board writer gave no ground mark for Anudi; the other spots place "
                        "them."]
    # board v20: one spot is enough to hold the stretch; the other person is told to keep one spot too
    words = mk.paragraph(b.stretches[0], kept, {"Kasun": "red", "Anudi": "blue"})
    assert mk.complete(b.stretches[0], kept) and "Kasun (the red mannequin) stands on the concrete pavement" in words
    assert "Anudi (the blue mannequin) also keeps ONE spot for all these shots" in words
    assert not mk.complete(b.stretches[0], []) and mk.paragraph(b.stretches[0], [], {}) == ""


def test_the_paragraph_is_the_labs_words():
    """lab/fixed_marks phase 0 `stretch_marks`, with the changes the module says (the gap sentence's own distance)."""
    b = scene4()
    kept, _ = mk.check(SPOTS, b)
    got = mk.paragraph(b.stretches[0], kept, {"Kasun": "red", "Anudi": "blue"})
    assert got == (
        "Ground marks (shots 1 to 15): nobody walks in these shots, so each person stands on ONE spot on the ground "
        "for all of them, and every panel of them shows them on that same spot, seen from its own camera. Small "
        "movements (a turn of the head or body, a lean, a shift of weight, half a step) stay within half a metre of "
        "the mark; the feet never travel further. Kasun (the red mannequin) stands on the concrete pavement half a "
        "metre in from the kerb drain, one step to the right of the rear of the food three-wheeler, whose open service "
        "hatch and the blue awning above it are directly behind him and to his left. Anudi (the blue mannequin) "
        "stands on the same pavement, the same half metre in from the drain, about 1.2 metres to Kasun's right, in "
        "front of the green building, with the pale boundary wall beginning just to her right. The gap between them "
        "is the same in every panel: a closer camera makes them larger, never closer together. What is behind each of "
        "them follows from these spots and the panel's camera.")
    assert not blocking(got)


def test_one_person_sitting_with_a_traveller_has_no_gap_and_sits():
    staging = {"marks": [mark(0, "Anudi", "sofa", "sitting"), mark(0, "Father", "living room", "walking")]}
    b = mk.stretches(staging, items(3), [shot("a", 1, 0, 1), shot("b", 2, 1, 3)])
    kept, _ = mk.check([{"stretch": 1, "who": "Anudi", "spot": "on the left end of the sofa"}], b)
    got = mk.paragraph(b.stretches[0], kept, {"Anudi": "blue"})
    assert got.startswith("Ground marks (shots 1 and 2): Small movements")
    assert "Anudi (the blue mannequin) sits on the left end of the sofa." in got
    assert "Father is on the move in these shots and holds no mark." in got and mk.GAP not in got


# ── the plate ─────────────────────────────────────────────────────────────────────────────────────────────────

VIEWS = [{"n": 1, "name": "Wide", "camera": "ANCHOR SPOT on the road, square on to the pavement"},
         {"n": 3, "name": "Looking right", "camera": "Same ANCHOR SPOT, turned right"},
         {"n": 4, "name": "Reverse", "camera": "Same ANCHOR SPOT, turned 180 degrees"}]


def test_the_plate_view_is_what_most_panels_face_else_the_anchor_wide():
    assert mk.plate_view([3, 1, 3, 0], VIEWS, "outside")["n"] == 3
    assert mk.plate_view([4, 3], VIEWS, "outside")["n"] == 4, "a tie goes to the earliest panel"
    assert mk.plate_view([0, 9], VIEWS, "outside")["n"] == 1
    assert mk.plate_view([0], VIEWS, "inside")["n"] == 1
    assert mk.plate_view([0], VIEWS, "both") is None and mk.plate_view([], VIEWS, "vehicle") is None


def test_a_board_takes_from_the_plate_only_the_spots():
    b = scene4()
    label = mk.plate_label(b.stretches[0])
    assert label == ("the blocking plate for shots 1 to 15: one still of this place, the people standing on their "
                     "ground marks")
    assert kit.board_job(label) == (
        "only where each person stands on the ground, what stands behind each of them and the gap between them; every "
        "panel of shots 1 to 15 keeps them on exactly these spots, seen from its own camera. Not its framing, its "
        "light or its poses")


def board_writer() -> kit.Writer:
    return kit.Writer.of({
        "world": "Fine rain on a Colombo roadside.", "geography": "The vending bay at left, the wall at right.",
        "panels": [{"shot": n, "zone": "roadside", "camera": f"Camera {n}.", "background": "the bay at left",
                    "picture": "The red mannequin faces the blue mannequin.", "view": 1,
                    "people": [{"name": "Kasun", "left_hand": "empty, at his side", "right_hand": "empty"},
                               {"name": "Anudi", "left_hand": "the clay umbrella's shaft",
                                "right_hand": "the clay phone"}]} for n in (1, 2)]})


def test_board_and_panel_prompts_carry_the_marks_and_are_unchanged_without():
    w = board_writer()
    colours = {"Kasun": "red", "Anudi": "blue"}
    plain = kit.board_prompt(w, [1, 2], [], colours)
    assert kit.board_prompt(w, [1, 2], [], colours, marks=(), panel_marks={}) == plain
    got = kit.board_prompt(w, [1, 2], [], colours, marks=["Ground marks (shots 1 to 15): X."],
                           panel_marks={2: "Marks: on the ground marks of shots 1 to 15."})
    assert got.index("Geography: ") < got.index("Ground marks (shots 1 to 15): X.") < got.index("PANEL 1 ")
    assert "PANEL 2 (row 1, column 2) — Marks: on the ground marks of shots 1 to 15. Camera 2." in got
    assert "PANEL 1 (row 1, column 1) — Camera 1." in got
    p = w.panel(1)
    assert kit.panel_prompt(w, p, [], colours, marks="", panel_mark="") == kit.panel_prompt(w, p, [], colours)
    one = kit.panel_prompt(w, p, [], colours, marks="Ground marks: Y.", panel_mark="Marks: Z.")
    assert "Ground marks: Y." in one and "THE PANEL — Marks: Z. Camera 1." in one


def test_the_plate_prompt_is_one_tall_still_from_the_view_with_the_first_panels_hands():
    b = scene4()
    kept, _ = mk.check(SPOTS, b)
    colours = {"Kasun": "red", "Anudi": "blue"}
    ground = mk.paragraph(b.stretches[0], kept, colours)
    labels = ["the location sheet for Colombo roadside: six named views of the one place"]
    w = board_writer()
    got = kit.plate_prompt(w, b.stretches[0], ground, labels, colours, VIEWS[0], w.panel(1), aspect=kit.TALL,
                           props=["umbrella", "phone"], views=[{"n": v["n"], "name": v["name"]} for v in VIEWS])
    assert got.startswith("One photorealistic film still for a Sri Lankan television drama, a tall portrait 9:16 frame")
    assert "This still is painted from view 1 (Wide)'s camera" in got and "Every panel below" not in got
    assert "Ground marks: Small movements" in got and "nobody walks" not in got
    assert "The camera: ANCHOR SPOT on the road, square on to the pavement, at standing eye height" in got
    assert ("Hands: the red mannequin: left hand empty, at his side; right hand empty. the blue mannequin: left hand "
            "the clay umbrella's shaft; right hand the clay phone.") in got
    assert "(every panel)" not in got and not blocking(got)
    wide = kit.plate_prompt(w, b.stretches[0], ground, [], colours, None, None)
    assert "a wide 16:9 frame" in wide and "The camera: the location plate's own camera" in wide


def test_the_pin_changes_with_the_spots_and_the_pictures_only():
    b = scene4()
    kept, _ = mk.check(SPOTS, b)
    s = b.stretches[0]
    colours = {"Kasun": "red", "Anudi": "blue"}
    a = mk.pin(s, kept, colours, ["views/1.png"])
    assert a == mk.pin(s, kept, dict(reversed(list(colours.items()))), ["views/1.png"])
    moved = [kept[0], kept[1].model_copy(update={"spot": "by the gate"})]
    assert mk.pin(s, moved, colours, ["views/1.png"]) != a
    assert mk.pin(s, kept, colours, ["views/2.png"]) != a


def test_the_writer_keeps_its_marks_and_plates_through_every_rebuild():
    raw = {"world": "w", "geography": "g", "conflicts": [], "panels": [{"shot": 1, "camera": "c", "background": "b",
                                                                         "picture": "p", "zone": "z", "people": []}],
           "marks": SPOTS, "plates": [{"n": 1, "path": "x/plate_1.png", "pin": "abc"}]}
    w = kit.Writer.of(raw)
    assert w.dump()["marks"] == SPOTS and w.dump()["plates"][0]["pin"] == "abc"
    old = kit.Writer.of({"world": "w", "geography": "g", "panels": []})
    assert "marks" not in old.dump(), "an old board dumps alike"
    merged = w.merged(kit.Writer.of({"world": "", "geography": "", "panels": []}), [1])
    assert merged.marks == w.marks and merged.plates == w.plates
    _, renumbered = kit.renumber([{"shot_id": "s1", "number": 1}], w, [{"id": "s1", "number": 2}])
    assert renumbered.marks == w.marks and renumbered.plates == w.plates


def test_the_writer_reads_the_stretches_in_its_bundle():
    staging = {"marks": [mark(0, "Kasun", "roadside", "standing"), mark(0, "Anudi", "roadside", "standing"),
                         mark(3, "Anudi", "roadside", "walking")]}
    got = mk.stretches(staging, items(5), [shot("a", 1, 0, 2), shot("b", 2, 2, 3), shot("c", 3, 3, 5)])
    rows = mk.stretch_rows(got)
    assert rows == [{"stretch": 1, "shots": [1, 2], "still": ["Kasun", "Anudi"], "ends": "Anudi moves before shot 3"},
                    {"stretch": 2, "shots": [3], "still": ["Kasun"], "on_the_move": ["Anudi"]}]
    bundle = kit.writer_bundle({"script": []}, [], [], {"name": "roadside"}, [], [], stretches=rows)
    assert bundle["stretches"] == rows
    assert "stretches" not in kit.writer_bundle({"script": []}, [], [], {"name": "roadside"}, [], [])


def test_a_spot_that_starts_with_its_own_verb_reads_once():
    """Board v20: "Kasun stands Standing on the same concrete landing strip"."""
    assert mk.clean_spot("Standing on the same concrete landing strip") == "on the same concrete landing strip"
    assert mk.clean_spot("  is sitting,  On the crate ") == "on the crate"
    assert mk.clean_spot("Beside the Kasun's stall") == "beside the Kasun's stall"
    assert mk.clean_spot("Kasun's stall side") == "Kasun's stall side", "a name keeps its capital"

