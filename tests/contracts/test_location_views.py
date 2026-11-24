"""plan/2026-11-24: a location's views sheet (the person's method, lab/location_views). Pure: rows in, words out."""
from __future__ import annotations

from typing import Any

from contracts import board as kit
from contracts import canon
from contracts.frame_brief import reference_job

VIEWS = [{"n": i, "name": n, "what": f"what {n.lower()} shows.", "box": [0, 0, 10, 10]}
         for i, n in enumerate(["Front wide", "Looking left", "Looking right", "Reverse", "Hatch detail",
                                "Ground detail"], 1)]


def place(**over: Any) -> dict[str, Any]:
    assets = [{"kind": "views", "path": "p/l/views/a.png", "views": VIEWS, "layout": "L", "light": "rain"},
              {"kind": "sheet", "path": "p/l/plate.png"}]
    return {"id": "loc", "kind": "location", "name": "Colombo roadside",
            "current": {"id": "v1", "version": 1, "reference_assets": assets}, **over}


def test_the_views_sheet_is_its_own_kind_and_the_plate_stays_the_plate():
    row = place()
    assert canon.views_asset(row)["path"] == "p/l/views/a.png"
    assert canon.view_of(row, 2)["name"] == "Looking left" and canon.view_of(row, 9) is None
    assert [a["path"] for a in canon.sheet_assets(row["current"]["reference_assets"])] == ["p/l/plate.png"]
    kept = canon.keep_assets([{"kind": "views", "path": f"v{i}"} for i in range(4)]
                             + [{"kind": "sheet", "path": "s"}, {"kind": "face", "path": "f"}])
    assert [a["path"] for a in kept] == ["v0", "v1", "s", "f"], "two views sheets kept, a sheet never pushed out"


def test_the_sheet_prompt_is_the_labs():
    prompt = canon.views_sheet_prompt("Colombo roadside", ["the location plate for Colombo roadside",
                                                           "the location plate for Food three-wheeler"],
                                      "The stall at left.", "Fine rain.", VIEWS)
    assert prompt.startswith("A location reference sheet for a Sri Lankan television drama: six photorealistic")
    assert "laid out in a grid 3 across and 2 down" in prompt and "no people, no figures" in prompt
    assert "Take from image 2 the Food three-wheeler exactly as shown; it stands in this place." in prompt
    assert "VIEW 4 (row 2, column 1) — Reverse: what reverse shows." in prompt
    assert "Light and weather (every view): Fine rain." in prompt and "Draw NO text of any kind" in prompt


def board(view: int) -> kit.Writer:
    return kit.Writer.of({"world": "w", "geography": "g", "conflicts": [], "panels": [
        {"shot": 1, "zone": "z", "camera": "Eye height.", "background": "The stall at left.",
         "picture": "The red mannequin stands.", "people": [], "view": view}]})


def test_the_board_names_the_sheet_and_each_panels_view_in_the_labs_words():
    w = board(1)
    assert w.panels[0].view == 1 and kit.Writer.of(w.dump()).panels[0].view == 1
    label = canon.views_label("Colombo roadside")
    prompt = kit.board_prompt(w, [1], [label], {}, kit.TALL, views=VIEWS)
    assert ("image 1 is the location sheet for Colombo roadside: six named views of the one place, numbered left to "
            "right, then top to bottom: view 1 Front wide; view 2 Looking left") in prompt
    assert "Every panel below names the view its background comes from" in prompt
    assert "Background view: view 1 Front wide." in prompt
    plain = kit.board_prompt(w, [1], ["the location plate for Colombo roadside"], {}, kit.TALL)
    assert "Background view" not in plain and "location sheet" not in plain, "no sheet, as before"


def test_a_panel_naming_a_view_the_sheet_has_not_is_reported():
    shots = [kit.BoardShot(id="s1", number=1, slate="", painted=True, text="", plan={"number": 1})]
    assert kit.writer_findings(board(7), shots, views=VIEWS) == [
        "Shot 1: names view 7, which the location sheet does not have."]
    assert kit.writer_findings(board(1), shots, views=VIEWS) == []


def test_a_frame_takes_the_background_from_its_view():
    label = canon.view_label("Colombo roadside", VIEWS[0])
    assert label == "view 1 (front wide) of the location sheet for Colombo roadside"
    assert reference_job(label) == canon.VIEW_JOB
