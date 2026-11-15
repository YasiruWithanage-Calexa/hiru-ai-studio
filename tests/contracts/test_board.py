"""The Scene board's pure rules (plan/2026-11-14 phase 1, `contracts/board.py`): parts, prompts, crops, pins, the
frame's paragraphs. Pictures are made here with Pillow; nothing is painted."""
from __future__ import annotations

import io

from PIL import Image

from contracts import board as kit
from contracts.frame_brief import plan_references, reference_job, references_block
from contracts.safe_depiction import blocking
from hiru_ai.systems.frame_render import pictures as pics


def writer(numbers: list[int], **people: str) -> kit.Writer:
    return kit.Writer.of({
        "world": "Heavy rain at dawn. The canal is brown. Nimal has a wide face and thick brows. The panels share a "
                 "grid with gutters.",
        "geography": "The path runs from screen left to the gate at screen right.",
        "panels": [{"shot": n, "zone": "path", "camera": f"Wide camera {n}.", "background": "the canal at left",
                    "picture": "The red mannequin lies still; the blue mannequin kneels beside its right hand.",
                    "people": [{"name": k, "state": v} for k, v in people.items()]} for n in numbers],
        "conflicts": ["Bag colour differs."]})


def board_png(cols: int, rows: int, w: int = 1536, h: int = 1024, gutter: int = 12) -> bytes:
    """A painted-looking board: grey panels on white, with even white gutters."""
    im = Image.new("RGB", (w, h), "white")
    cw, ch = (w - gutter * (cols - 1)) // cols, (h - gutter * (rows - 1)) // rows
    for r in range(rows):
        for c in range(cols):
            x, y = c * (cw + gutter), r * (ch + gutter)
            im.paste(Image.new("RGB", (cw, ch), (60 + 10 * (r * cols + c), 80, 90)), (x, y))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_grid_and_parts_follow_d5():
    assert kit.grid_for(9) == (3, 3) and kit.grid_for(16) == (4, 4) and kit.grid_for(10) == (4, 3)
    assert kit.parts_of(list(range(16))) == [list(range(16))]
    two = kit.parts_of(list(range(17)))
    assert [len(p) for p in two] == [12, 6] and two[0][-1] == two[1][0] == 11, "one overlap panel"
    three = kit.parts_of(list(range(30)))
    assert all(len(p) <= 12 for p in three) and three[1][0] == three[0][-1] and three[2][0] == three[1][-1]
    assert sorted({x for p in three for x in p}) == list(range(30))


def test_a_black_plate_is_never_a_panel():
    scene = {"script": [{"text": "Aruni walks."}, {"text": "Cut to black."}]}
    shots = [{"id": "a", "number": 1, "block_start": 0, "block_end": 1, "ir": {"setting": "canal"}},
             {"id": "b", "number": 2, "block_start": 1, "block_end": 2}]
    got = kit.board_shots(scene, shots, [], {"a": ["Aruni"]}, plates=["b"])
    assert [s.painted for s in got] == [True, False] and got[1].text == "Cut to black." and not got[1].plan
    bundle = kit.writer_bundle(scene, got, [], {"name": "canal"}, [], [])
    assert [s["number"] for s in bundle["shots"]] == [1], "the writer never sees a black plate"


def test_the_board_prompt_is_mannequins_numbered_by_position_and_safe():
    w = writer([1, 2, 3], Nimal="eyes closed, still")
    colours = kit.colours_for(["Nimal", "Aruni"])
    assert colours == {"Nimal": "red", "Aruni": "blue"}
    prompt = kit.board_prompt(w, [1, 2, 3], ["the location plate for Canal", "the reference sheet for Key"], colours)
    assert "PANEL 3 (row 2, column 1)" in prompt and "Nimal is the red mannequin" in prompt
    assert "image 1: the kind of place" in prompt and "image 2: Key exactly as shown" in prompt
    assert "wide face" not in prompt, "a sentence about a face never reaches a board"
    assert "Draw NO text" in prompt and not blocking(prompt)
    note = kit.writer_message({"shots": [{}, {}, {}]}, colours, repaint={2: "side-on"})
    assert "MANNEQUIN BOARD" in note and "- shot 2: side-on" in note and "3 panels" in note


def test_cells_are_cut_along_the_painted_gutters():
    png = board_png(3, 2)
    boxes = pics.cell_boxes(png, 6)
    assert len(boxes) == 6
    x0, y0, _x1, _y1 = boxes[4]
    assert 500 < x0 < 530 and 500 < y0 < 530, boxes[4]
    cell = Image.open(io.BytesIO(pics.crop(png, boxes[0])))
    assert cell.getpixel((5, 5)) != (255, 255, 255) and cell.getpixel((cell.width - 3, cell.height - 3)) != (
        255, 255, 255), "no gutter left in a cell"


def test_the_sheet_holds_every_shot_with_black_cells():
    shots = [kit.BoardShot("a", 1, "", True, ""), kit.BoardShot("b", 2, "", False, "Cut to black.")]
    png = pics.scene_sheet(shots, {"a": pics.crop(board_png(1, 1), (0, 0, 384, 216))})
    im = Image.open(io.BytesIO(png))
    assert im.width > 2 * 384 - 1 and im.height >= 216


def test_the_repaint_mask_is_transparent_only_over_the_changed_cells():
    mask = Image.open(io.BytesIO(pics.repaint_mask((300, 200), [(0, 0, 100, 100)])))
    assert mask.mode == "RGBA" and mask.size == (300, 200)
    assert mask.getpixel((50, 50))[3] == 0 and mask.getpixel((200, 150))[3] == 255


def test_pins_say_which_panel_is_out_of_date():
    s1 = {"id": "a", "number": 1, "framing": "WIDE", "block_start": 0, "block_end": 1, "ir": {"setting": "canal"}}
    s2 = {"id": "b", "number": 2, "framing": "MCU", "block_start": 1, "block_end": 2, "ir": {"setting": "gate"}}
    cells = [kit.new_cell(kit.BoardShot("a", 1, "", True, ""), s1, 1),
             kit.new_cell(kit.BoardShot("b", 2, "", True, ""), s2, 2)]
    assert not kit.stale_cells(cells, [s1, s2]).any
    changed = dict(s2, ir={"setting": "the gate at night"})
    stale = kit.stale_cells(cells, [s1, changed])
    assert stale.changed == [2] and not stale.whole and stale.reasons() == ["shot 2 changed"]
    camera_only = dict(s2, camera_overrides={"lens": "50mm"}, version=9)
    assert not kit.stale_cells(cells, [s1, camera_only]).any, "only what the writer read pins a panel"
    s3 = {"id": "c", "number": 3, "block_start": 2, "block_end": 3}
    added = kit.stale_cells(cells, [s1, s2, s3])
    assert added.whole and added.added == [3]
    moved = kit.stale_cells(cells, [dict(s1, number=2), dict(s2, number=1)])
    assert moved.order and moved.whole
    assert kit.stale_cells(cells, [s1]).removed == [2]


def test_a_frame_from_a_panel_names_people_keeps_their_state_and_drops_the_board():
    w = writer([1], Nimal="eyes closed, still")
    sections = kit.frame_sections(w, 1, {"Nimal": "red", "Aruni": "blue"}, ["Aruni kneels at the gate."],
                                  faced=["Nimal"])
    text = " ".join(sections)
    assert "Nimal is the red mannequin" in sections[0] and "face sheet" in sections[0]
    assert "Aruni kneels at the gate." in sections[1] and "Nimal: eyes closed, still." in sections[1]
    assert "This shot: Wide camera 1." in text and "Nimal lies still; Aruni kneels" in text
    assert "grid" not in sections[2] and "gutters" not in sections[2], "the board's own words never reach a frame"
    assert kit.state_line(["Nimal lies still, eyes closed."], [kit.PanelPerson("Nimal", "eyes closed")]).count(
        "eyes closed") == 1, "a state the plan already says is not said twice"
    assert kit.frame_sections(w, 9, {}, []) == []


def test_unmannequin_turns_colours_back_into_people():
    out = kit.unmannequin("The red mannequin's red head turns; the blue mannequin kneels.", {"Nimal": "red",
                                                                                              "Aruni": "blue"})
    assert out == "Nimal's head turns; Aruni kneels."


def test_the_face_sheet_goes_first_owns_the_face_and_hair_follows_the_look():
    row = {"id": "n", "kind": "character", "name": "Nimal",
           "current": {"reference_assets": [{"path": "face.png", "kind": "face"}, {"path": "base.png"}]}}
    place = {"id": "l", "kind": "location", "name": "Canal", "current": {"reference_assets": [{"path": "plate.png"}]}}
    scene = {"location_id": "l", "script": [{"text": "Nimal lies by the gate."}]}
    shot = {"id": "s", "block_start": 0, "block_end": 1}
    planned = plan_references(scene, shot, [row, place], ["n"], {})
    assert [p.role for p in planned][:2] == ["face", "character"] and planned[0].choices[0][1] == "face.png"
    assert planned[1].choices[0][1] == "base.png", "a face sheet is never taken for the base sheet"
    labels = [p.label for p in planned]
    assert "face, age and hair" in reference_job(labels[0], labels)
    assert reference_job(labels[0], labels, ["Nimal"]).startswith("Nimal's face and age at")
    look = "the look sheet for Nimal"
    assert "clothes, shoes and accessories and hair" in reference_job(look, [labels[0], look], ["Nimal"])
    assert "not the face" in reference_job(look, [labels[0], look])
    block = " ".join(references_block([labels[0], look]))
    assert "face sheet shows that person's face" in block and "same clothes and accessories" in block


def test_someone_only_heard_never_gets_a_face_sheet():
    row = {"id": "n", "kind": "character", "name": "Nimal",
           "current": {"reference_assets": [{"path": "face.png", "kind": "face"}, {"path": "base.png"}]}}
    planned = plan_references({"script": []}, {"id": "s", "block_start": 0, "block_end": 0}, [row], [], {})
    assert not [p for p in planned if p.role == "face"]
