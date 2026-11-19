"""plan/2026-11-17 phase 1: the pure steps of a board update (`contracts/board.py`). An edited, added, removed or moved
shot never repaints the whole board: its panel is painted alone (`panel_prompt`, `writer_message(edit=...)`) and code
renumbers, keeps the colours and restores an undone picture. Nothing is painted here."""
from __future__ import annotations

import json
from pathlib import Path

from contracts import board as kit
from contracts.safe_depiction import blocking

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "lab" / "panel_edit"


def shot(sid: str, number: int, setting: str = "canal") -> dict:
    return {"id": sid, "number": number, "framing": "WIDE", "block_start": number - 1, "block_end": number,
            "ir": {"setting": setting}}


def cell(sid: str, number: int, row: dict | None = None, **more: object) -> dict:
    return {"shot_id": sid, "number": number, "kind": "painted", "panel": number, "box": [0, 0, 1, 1],
            "path": f"p/cell_{number:03d}.png", "pin": kit.plan_pin(row or shot(sid, number)), "locked": False,
            "note": "", "text": "", **more}


def board(numbers: list[int]) -> kit.Writer:
    return kit.Writer.of({"world": "Dawn. The board has six panels with gutters. The canal is brown.",
                          "geography": "The path runs left to right.",
                          "panels": [{"shot": n, "zone": "z", "camera": f"Camera {n}.", "background": "b",
                                      "picture": f"Picture {n}.", "people": []} for n in numbers]})


# ── renumber: cells and writer panels move together (§3.5) ─────────────────────────────────────────────────────


def test_renumber_holds_the_writer_and_the_cells_together():
    """For every painted cell, `writer.panel(cell.number)` is the panel written for that shot id."""
    cells = [cell("a", 1), cell("b", 2), cell("c", 3)]
    writer = board([1, 2, 3])
    words = {c["shot_id"]: writer.panel(c["number"]).picture for c in cells}  # type: ignore[union-attr]
    # shot "new" inserted at 2, "b" removed: a -> 1, new -> 2, c -> 3 ... then c moved before a
    now = [shot("c", 1), shot("a", 2), shot("new", 3)]
    got, w = kit.renumber(cells, writer, now)
    assert [(c["shot_id"], c["number"]) for c in got] == [("a", 2), ("b", 2), ("c", 1)], "a gone shot keeps its number"
    kept = [c for c in got if c["shot_id"] != "b"]
    for c in kept:
        assert w.panel(c["number"]).picture == words[c["shot_id"]]  # type: ignore[union-attr]
    assert [p.shot for p in w.panels] == [1, 2], "the removed shot's panel is dropped, the rest in order"
    again, w2 = kit.renumber(kept, w, now)
    assert again == kept and w2.dump() == w.dump(), "renumbering twice changes nothing"


def test_renumber_follows_the_overlap_panel_in_both_parts():
    part1 = [cell("a", 1), cell("b", 2)]
    part2 = [cell("b", 2), cell("c", 3)]
    got, w = kit.renumber([*part1, *part2], board([1, 2, 3]), [shot("x", 1), shot("a", 2), shot("b", 3),
                                                                shot("c", 4)])
    assert [c["number"] for c in got] == [2, 3, 3, 4] and [p.shot for p in w.panels] == [2, 3, 4]


# ── colours (§3.4) ───────────────────────────────────────────────────────────────────────────────────────────────


def test_saved_colours_win_and_a_new_person_takes_the_first_free_one():
    saved = {"nimal": "red", "aruni": "blue"}
    got = kit.keep_colours(saved, ["kasun", "aruni", "nimal"])
    assert got == {"nimal": "red", "aruni": "blue", "kasun": "yellow"}, "a person added to an early shot shifts nothing"
    assert kit.keep_colours({"a": "blue"}, ["b", "a"]) == {"a": "blue", "b": "red"}
    many = kit.keep_colours({}, [f"p{i}" for i in range(8)])
    assert list(many.values())[:6] == list(kit.COLOURS) and len(many) == 8
    assert kit.keep_colours({"gone": "green"}, ["x"])["gone"] == "green", "someone who left keeps their colour"


# ── insert, previous ─────────────────────────────────────────────────────────────────────────────────────────────


def test_an_added_shot_joins_the_part_of_the_shot_before_it():
    parts = [[cell("a", 1), cell("b", 2)], [cell("b", 2), cell("c", 3)]]
    shots = [shot("new0", 1), shot("a", 2), shot("b", 3), shot("new", 4), shot("c", 5)]
    assert kit.insert_position(parts, shots, "new") == 0, "the part that holds the shot before it (b: first owner)"
    assert kit.insert_position(parts, shots, "new0") == 0, "a new first shot joins the first part"
    shots2 = [*shots, shot("last", 6)]
    assert kit.insert_position(parts, shots2, "last") == 1


def test_undo_finds_the_picture_painted_for_that_plan():
    c = cell("a", 1, previous=[{"pin": "p-old", "path": "p/old.png", "panel": {"shot": 1, "camera": "Old."}}])
    assert kit.previous_for(c, "p-old") == {"pin": "p-old", "path": "p/old.png", "panel": {"shot": 1, "camera": "Old."}}
    assert kit.previous_for(c, "other") is None and kit.previous_for(c, "") is None
    history = kit.remember(c, kit.Panel(1, "z", "Now.", "b", "p"))
    assert history[0] == {"pin": c["pin"], "path": c["path"], "panel": {
        "shot": 1, "zone": "z", "camera": "Now.", "background": "b", "picture": "p", "people": []}}
    long = c
    for i in range(5):
        long = {**long, "pin": f"pin{i}", "path": f"p/{i}.png", "previous": kit.remember(long, None)}
    assert len(long["previous"]) == kit.PREVIOUS_KEPT


# ── the new Stale ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_locked_panel_is_named_and_never_painted():
    rows = [shot("a", 1), shot("b", 2)]
    cells = [cell("a", 1, rows[0], locked=True), cell("b", 2, rows[1])]
    changed = [shot("a", 1, "the gate at night"), shot("b", 2, "the kitchen")]
    st = kit.stale_cells(cells, changed)
    assert st.changed == [1, 2] and st.locked == [1] and st.paint == ["b"]
    assert st.reasons() == ["shot 2 changed", "shot 1 is locked and out of date: unlock to update"]
    assert st.items() == [(1, "locked"), (2, "changed")]
    only_locked = kit.stale_cells(cells, [changed[0], rows[1]])
    assert only_locked.any and not only_locked.updatable, "a locked panel alone gives an update nothing to do"


def test_a_black_plate_that_changes_is_seen():
    row = shot("a", 1)
    black = kit.new_cell(kit.BoardShot("a", 1, "", False, "Cut to black."), row, None)
    assert black["pin"] and black["source"] == "sheet"
    st = kit.stale_cells([black], [shot("a", 1, "a lane")])
    assert st.changed == [1] and st.paint == ["a"]
    old = dict(black, pin="")  # a board painted before plan/2026-11-17: its plates carry no pin
    assert not kit.stale_cells([old], [shot("a", 1, "a lane")]).any


# ── one panel: the writer's message and the image prompt (§3.2) ───────────────────────────────────────────────


def test_the_one_panel_message_fixes_the_board_and_ends_with_the_instructions():
    edit = kit.Edit(kind="change", number=2, plan={"number": 2, "setting": "gate"}, board=board([1, 2, 3]),
                    pictures=["the location plate for Canal", kit.writer_neighbour_label("before", 1)],
                    before=1, after=3, note="side-on")
    text = kit.writer_message({}, {"Nimal": "red"}, edit=edit)
    assert text.endswith(kit.ONE_PANEL), "the one-panel rules go last: the system prompt is unchanged"
    fixed = json.loads(text.split("<approved_board>\n")[1].split("\n</approved_board>")[0])
    assert [p.get("being_replaced", False) for p in fixed["panels"]] == [False, True, False]
    assert "image 2: panel 1 of the approved board (just before this one)" in text
    assert "The person's note for this panel: side-on" in text and "Nimal = the red mannequin" in text
    add = kit.writer_message({}, {}, edit=kit.Edit(kind="add", number=4, plan={}, board=board([1, 2, 3, 5]),
                                                   before=3, after=5))
    assert "ADD. Shot 4 is a new shot, between shot 3 and shot 5." in add and "being_replaced" not in add
    answer = kit.panel_answer({"world": "ignored", "geography": "",
                               "panels": [{"shot": 9, "zone": "z", "camera": "C.", "background": "B.",
                                           "picture": "P.", "people": []}], "conflicts": []}, 4)
    assert answer is not None and answer.shot == 4, "the shot's number now, not the writer's"
    assert kit.panel_answer({"panels": []}, 4) is None


def test_the_panel_prompt_is_one_still_and_drops_the_sheet_words():
    labels = ["the location plate for Canal", kit.neighbour_label("before", 1), kit.neighbour_label("after", 3)]
    prompt = kit.panel_prompt(board([1, 2, 3]), board([2]).panels[0], labels, {"Nimal": "red"})
    assert "a single wide landscape 16:9 panel" in prompt and kit.CAMERA_RULE in prompt
    assert "six panels" not in prompt and "World: Dawn. The canal is brown." in prompt
    assert "image 3 is the approved storyboard panel just after this one (shot 3)" in prompt
    assert kit.NEIGHBOURS in prompt and "no borders, no gutters" in prompt and not blocking(prompt)
    alone = kit.panel_prompt(board([1]), board([1]).panels[0], ["the location plate for Canal"], {}, kit.TALL)
    assert kit.NEIGHBOURS not in alone and "tall portrait 9:16" in alone, "a one-shot scene has no neighbour"


def test_the_panel_prompt_matches_the_labs_run_002_add():
    """Golden: the same input as lab/panel_edit run_002 `add_solo` gives the very prompt the lab painted."""
    golden = LAB / "runs" / "run_002" / "add_solo_prompt.txt"
    if not golden.exists():  # the lab may be deleted (its README): nothing to compare with
        return
    raw_board = json.loads((LAB / "input" / "scene1" / "board.json").read_text(encoding="utf-8"))
    edits = json.loads((LAB / "input" / "scene1" / "edits.json").read_text(encoding="utf-8"))
    refs = json.loads((LAB / "input" / "scene1" / "refs.json").read_text(encoding="utf-8"))
    raw_panel = json.loads((LAB / "runs" / "run_002" / "writer_add.json").read_text(encoding="utf-8"))
    panel = kit.panel_of(raw_panel, 100)
    assert panel is not None
    after = int(edits["add"]["after"])
    labels = [*(f"the location plate for {r['name']}" for r in refs), kit.neighbour_label("before", after),
              kit.neighbour_label("after", after + 1)]
    prompt = kit.panel_prompt(kit.Writer.of(raw_board["writer"]), panel, labels, edits["colours"], kit.TALL)
    # 2026-11-18 (lab/action_budget): the weather is the panel's own, so a dry panel beside a rainy neighbour stays
    # dry. Only that sentence differs from what the lab painted.
    lab_neighbours = ("The approved storyboard panels attached last sit next to this one on the same board. Paint this "
                      "panel so it sits beside them unnoticed: the same mannequins in the same colours and finish, the "
                      "same place, props, light, weather, colour grade and level of detail. Do not copy their framing: "
                      "this panel has its own camera, described below.")
    assert prompt == golden.read_text(encoding="utf-8").replace(lab_neighbours, kit.NEIGHBOURS)
