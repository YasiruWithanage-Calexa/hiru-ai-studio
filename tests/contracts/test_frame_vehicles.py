"""plan/2026-11-24b phase 4: the first frame's pictures and words for its vehicles (lab/vehicle_role runs 002 and 005).
Scene 2 shot 1 is INSIDE the BMW: its plate is THE place, the roadside plate is not attached. Scene 4 shot 1 has the
three-wheeler `at` the roadside: the roadside plate leads, the vehicle plate follows with the vehicle-only job. Pure."""
from __future__ import annotations

from typing import Any

from contracts import vehicles as vh
from contracts.frame_brief import INSIDE_NOTE, plan_references, reference_job

ANUDI, ROAD, CAR, TUK = "anudi", "road", "car", "tuk"
CANON: list[dict[str, Any]] = [
    {"id": ANUDI, "kind": "character", "name": "Anudi", "current": {"reference_assets": [{"path": "p/anudi.png"}],
                                                                    "card": {}}},
    {"id": ROAD, "kind": "location", "class": "set", "name": "Colombo roadside",
     "current": {"reference_assets": [{"path": "p/road.png"}], "card": {"look": "asphalt"}}},
    {"id": CAR, "kind": "location", "class": "vehicle", "name": "Family car",
     "current": {"reference_assets": [{"path": "p/car.png"}],
                 "card": {"look": "a pearl-silver sedan, right-hand drive", "make": "BMW 520d, 2019, pearl silver"}}},
    {"id": TUK, "kind": "location", "class": "vehicle", "name": "Food three-wheeler",
     "current": {"reference_assets": [{"path": "p/tuk.png"}], "card": {"look": "a maroon three-wheeler"}}},
]
SCENE = {"id": "s2", "location_id": ROAD, "script": []}
CAR_PLATE = "the vehicle plate for Family car (BMW 520d, 2019, pearl silver)"


def shot(vehicles: list[dict[str, str]] | None, setting: str = "") -> dict[str, Any]:
    ir: dict[str, Any] = {"setting": setting, "first_frame": {}, "subjects": []}
    if vehicles is not None:
        ir["vehicles"] = vehicles
    return {"id": "sh", "ir": ir, "person_edits": {}, "block_start": 0, "block_end": 0}


def labels(s: dict[str, Any]) -> list[str]:
    return [p.label for p in plan_references(SCENE, s, CANON, [ANUDI], {}, faces=False)]


def test_scene_2_shot_1_inside_the_car_has_no_roadside_plate():
    got = labels(shot([{"id": CAR, "role": "inside", "where": ""}]))
    assert got == ["the character sheet for Anudi", CAR_PLATE + INSIDE_NOTE]
    assert reference_job(got[1]) == vh.INSIDE_JOB


def test_scene_4_shot_1_the_roadside_leads_and_the_three_wheeler_follows_with_the_vehicle_only_job():
    got = labels(shot([{"id": TUK, "role": "at", "where": "parked side-on in the vending bay"}]))
    assert got == ["the character sheet for Anudi", "the location plate for Colombo roadside",
                   "the vehicle plate for Food three-wheeler"]
    assert reference_job(got[2]) == vh.job("at") and vh.job("at").startswith("ONLY the vehicle itself")


def test_an_older_shot_finds_the_vehicle_by_name_as_at_never_as_a_second_location():
    got = labels(shot(None, setting="Anudi walks past the Food three-wheeler on the roadside."))
    assert got[-1] == "the vehicle plate for Food three-wheeler"
    assert "the location plate for Food three-wheeler" not in got


def test_the_brief_says_inside_and_where():
    car = vh.ShotVehicle(id=CAR, name="Family car", make="BMW 520d, 2019, pearl silver", role="inside")
    lines = vh.frame_lines([car], {c["id"]: c for c in CANON}, "Colombo roadside")
    assert lines[0].startswith("The place: this shot happens INSIDE the Family car (BMW 520d, 2019, pearl silver).")
    assert lines[0].endswith(vh.SEAT_RIGHT), "a right-hand-drive car: the driver at frame LEFT looking back"
