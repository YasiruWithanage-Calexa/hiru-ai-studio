"""plan/2026-11-24b phase 3: the board sees its vehicles (lab/vehicle_role runs 001 and 004). The vehicle's own plate
goes after the place's, with the vehicle-only job; a vehicle is never clay; one "Vehicles (every panel):" line before
Geography says panel by panel where each one is; the writer reads each vehicle's card and each shot's role. Fakes
only: a scripted writer, a painter that returns a real gridded PNG. Nothing is paid for."""
from __future__ import annotations

import json
from typing import Any

from contracts import vehicles as vh
from hiru_ai.core.fakes import FakeImages
from tests.contracts.test_board import board_png
from tests.hiru_ai.test_scene_board import BoardStore, numbers, reply, run
from tests.services.frame_render.test_frame_render import shots

CAR_ID = "car-1"
KERB = "stopped on the asphalt beside the kerb drain, nose toward screen right"


def with_car(store: BoardStore, views: bool = False) -> None:
    """The scene 2 case: shot 1 INSIDE the family car, shot 2 the car `at` the kerb, the others no car."""
    assets: list[Any] = [{"kind": "sheet", "path": "p/car/plate.png"}]
    if views:
        assets.insert(0, {"kind": "views", "path": "p/car/views.png", "template": "vehicle", "views": [
            {"n": i, "name": n, "camera": "c", "sees": f"{n} of the car.", "what": f"c {n} of the car.",
             "box": [0, 0, 500, 330]} for i, n in enumerate(["Front three-quarter", "Side", "Rear three-quarter",
                                                             "Inside from the rear", "Inside from the front",
                                                             "Detail"], 1)]})
    store.canon_rows.append({
        "id": CAR_ID, "kind": "location", "class": "vehicle", "code": "L09", "name": "Family car", "aliases": [],
        "locked": False, "current": {"id": "car-v1", "version": 1, "reference_assets": assets, "card": {
            "look": "A pearl-silver four-door sedan, beige seats, right-hand-drive steering wheel.",
            "make": "BMW 520d, 2019, pearl silver"}}})
    rows = shots(store)
    rows[0]["ir"] = {**rows[0]["ir"], "vehicles": [{"id": CAR_ID, "role": "inside", "where": ""}]}
    rows[1]["ir"] = {**rows[1]["ir"], "vehicles": [{"id": CAR_ID, "role": "at", "where": KERB}]}
    for r in rows[2:]:
        r["ir"] = {**r["ir"], "vehicles": []}


def paint(store: BoardStore) -> tuple[str, list[str], Any]:
    bid = store.add_board()
    painter = FakeImages()
    painter.picture = board_png(2, 2)
    result, (_jobs, recorded) = run(store, {"board_id": bid}, [reply(numbers(store))], painter)
    assert result["status"] == "done", (result, store.board_rows[bid].get("error"))
    prompt, _, refs = painter.calls[-1]
    return prompt, [r.label for r in refs], recorded


def test_the_vehicle_plate_follows_the_place_and_is_never_clay():
    store = BoardStore()
    with_car(store)
    prompt, labels, recorded = paint(store)
    plate = "the vehicle plate for Family car (BMW 520d, 2019, pearl silver)"
    assert labels == ["the location plate for Kamala's house", plate]
    assert f"image 2: {vh.job('at', board=True)}" in prompt, "the vehicle-only job, with its inside"
    assert vh.CLAY_NEW in prompt and "full-size white clay vehicle" not in prompt
    line = next(p for p in prompt.split("\n\n") if p.startswith("Vehicles (every panel):"))
    assert prompt.index(line) < prompt.index("Geography: "), "the vehicles line comes before Geography"
    assert ("PANEL 1 is INSIDE the Family car: the vehicle is the place, its inside exactly as image 2 shows it; the "
            "street is seen only through the windows. " + vh.SEAT_RIGHT) in line
    assert f"PANEL 2: the Family car is {KERB}, all its wheels on the asphalt, the same vehicle as image 2." in line
    assert "PANEL 3" not in line
    sent = json.dumps([str(m.content) for call in recorded.calls for m in call], ensure_ascii=False)
    assert "BMW 520d, 2019, pearl silver" in sent and '\\"role\\": \\"inside\\"' in sent, \
        "the writer reads the card's make and each shot's role"


def test_a_vehicle_with_a_views_sheet_is_attached_as_its_sheet():
    store = BoardStore()
    with_car(store, views=True)
    _, labels, _ = paint(store)
    assert labels[1] == vh.sheet_label("Family car", "BMW 520d, 2019, pearl silver")


def test_a_scene_with_no_vehicle_paints_as_before():
    store = BoardStore()
    prompt, labels, _ = paint(store)
    assert labels == ["the location plate for Kamala's house"] and "Vehicles (every panel)" not in prompt
