"""plan/2026-11-24b phases 1-2: a shot's vehicles and the role of each (lab/vehicle_role, lab/final_views). Love Hour's
two cases: scene 4, the food three-wheeler `at` the roadside in shots 1-6; scene 2, shot 1 INSIDE the BMW, shots 2-5 the
BMW `at` the kerb, 6-7 the three-wheeler `at` the bay. Pure: rows in, words out."""
from __future__ import annotations

from typing import Any

from contracts import vehicles as vh
from contracts.canon import CanonCard
from contracts.producer import PersonEdits
from contracts.raphael.bin import Bin
from contracts.raphael.checks import vehicles as vehicle_faults
from contracts.raphael.scene import BlockS, SceneS, VehicleS, listing, scene_dump

CAR_LOOK = ("BMW 520d. 2019 version,  A well-kept pearl-silver midsize four-door sedan with a roomy beige fabric rear "
            "bench, charcoal dashboard, right-hand-drive steering wheel, black floor mats and lightly tinted windows.")
TUK_LOOK = "A compact older maroon three-wheeler with a black vinyl roof and a side hatch food counter."


def card(cid: str, name: str, look: str, make: str = "", cls: str = "vehicle") -> dict[str, Any]:
    return {"id": cid, "kind": "location", "class": cls, "name": name, "aliases": [],
            "current": {"card": {"look": look, **({"make": make} if make else {})}}}


CAR = card("car", "Family car", CAR_LOOK, "BMW 520d, 2019, pearl silver")
TUK = card("tuk", "Food three-wheeler", TUK_LOOK, "older maroon Bajaj three-wheeler")
ROAD = card("road", "Colombo roadside", "Patched asphalt.", cls="set")
CANON = [CAR, TUK, ROAD]
KERB = "stopped on the asphalt beside the kerb drain, all four wheels on the road, nose toward screen right"
BAY = "parked side-on in the vending bay at the left of the pavement, its wheels on the bay's concrete"


def shot(vehicles: Any = None, words: str = "", edits: Any = None) -> dict[str, Any]:
    ir: dict[str, Any] = {"setting": words}
    if vehicles is not None:
        ir["vehicles"] = vehicles
    return {"ir": ir, "person_edits": edits or {}}


def roles(s: dict[str, Any]) -> list[tuple[str, str]]:
    return [(v.name, v.role) for v in vh.shot_vehicles(s, CANON, PersonEdits.of(s).vehicles)]


def test_the_card_has_a_make_and_a_vehicle_is_named_with_it():
    assert CanonCard(make="BMW 520d, 2019, pearl silver").make.startswith("BMW")
    assert vh.make_of(CAR) == "BMW 520d, 2019, pearl silver" and vh.make_of(ROAD) == ""
    assert vh.plate_label("Family car", vh.make_of(CAR)) == \
        "the vehicle plate for Family car (BMW 520d, 2019, pearl silver)"


def test_raphaels_names_become_ids_one_inside_at_most_and_strangers_dropped():
    wire = [{"name": "Family car (BMW 520d)", "role": "inside", "where": ""},
            {"name": "Food three-wheeler", "role": "inside", "where": ""},
            {"name": "A red bus", "role": "at", "where": "on the road"},
            {"name": "family car", "role": "at", "where": KERB}]
    assert vh.from_wire(wire, CANON) == [{"id": "car", "name": "Family car", "role": "inside", "where": ""}]


def test_scene_2_the_role_changes_shot_by_shot():
    inside = shot([{"id": "car", "role": "inside", "where": ""}])
    at_kerb = shot([{"id": "car", "role": "at", "where": KERB}])
    bay = shot([{"id": "tuk", "role": "at", "where": BAY}])
    assert roles(inside) == [("Family car", "inside")]
    assert roles(at_kerb) == [("Family car", "at")] and roles(bay) == [("Food three-wheeler", "at")]
    assert roles(shot([])) == [], "Raphael said none: no fallback"


def test_scene_4_an_older_shot_finds_its_vehicle_by_name_never_inside():
    old = shot(words="Kasun at the Food three-wheeler's serving hatch, the wall at right.")
    assert roles(old) == [("Food three-wheeler", "at")]
    assert vh.shot_vehicles(old, CANON)[0].where == ""


def test_a_persons_change_wins_and_none_takes_a_vehicle_out():
    s = shot([{"id": "car", "role": "at", "where": KERB}],
             edits={"vehicles": [{"id": "car", "role": "inside"}, {"id": "tuk", "role": "at", "where": BAY}]})
    assert roles(s) == [("Family car", "inside"), ("Food three-wheeler", "at")]
    gone = shot([{"id": "car", "role": "at", "where": KERB}], edits={"vehicles": [{"id": "car", "role": "none"}]})
    assert roles(gone) == []
    assert PersonEdits.of(s).dump()["vehicles"][1] == {"id": "tuk", "role": "at", "where": BAY}


def test_where_must_name_what_it_stands_on():
    assert vh.surface_of(KERB) == "the asphalt" and vh.surface_of(BAY) == "the bay's concrete"
    assert vh.surface_of("parked in the vending bay") == "the vending bay"
    assert vh.surface_of("stopped at the kerb, nose right") == ""
    assert vh.where_findings([{"name": "Family car", "role": "at", "where": "stopped at the kerb"}]) == [
        "Family car: say what it stands on (the road, the asphalt, the bay's concrete, the ground) in `where`, so all "
        "its wheels stand on it."]
    assert vh.where_findings([{"name": "Family car", "role": "inside", "where": ""}]) == []
    assert vh.wheels("stopped at the kerb") == ", all its wheels on the ground"


def test_seat_sides_right_hand_drive_by_default_flipped_by_a_left_hand_drive_card():
    assert vh.seat_sentence(CAR) == vh.SEAT_RIGHT
    assert vh.SEAT_RIGHT.startswith("The driver's seat is on the car's RIGHT (right-hand drive): with the camera "
                                    "looking BACK from the front, the driver is at frame LEFT")
    lhd = card("jeep", "Army jeep", "An olive left-hand drive jeep with canvas seats.")
    assert vh.seat_sentence(lhd) == vh.SEAT_LEFT
    assert vh.seat_sentence(TUK) == "", "a three-wheeler's driver sits in the middle"


def test_the_board_line_is_the_labs():
    car = vh.ShotVehicle(id="car", name="Family car", make="BMW 520d, 2019, pearl silver", role="inside")
    kerb = car.model_copy(update={"role": "at", "where": KERB})
    tuk = vh.ShotVehicle(id="tuk", name="Food three-wheeler", role="at", where=BAY)
    line = vh.board_line([(1, [car]), (2, [kerb]), (3, [tuk])], {"car": 2, "tuk": 3}, {"car": CAR, "tuk": TUK})
    assert line.startswith("Vehicles (every panel): every vehicle is real, never clay, exactly as its vehicle plate "
                           "shows it: the Family car (BMW 520d, 2019, pearl silver) is image 2; the Food "
                           "three-wheeler is image 3. Where each one is, panel by panel: PANEL 1 is INSIDE the Family "
                           "car: the vehicle is the place, its inside exactly as image 2 shows it; the street is seen "
                           "only through the windows. The driver's seat is on the car's RIGHT")
    assert f"PANEL 2: the Family car is {KERB}, all its wheels on the asphalt, the same vehicle as image 2." in line
    assert f"PANEL 3: the Food three-wheeler is {BAY}, all its wheels on the bay's concrete" in line
    assert vh.board_line([(1, [])], {}, {}) == ""


def test_the_frame_words_inside_and_at():
    car = vh.ShotVehicle(id="car", name="Family car", make="BMW 520d", role="inside")
    inside = vh.frame_lines([car], {"car": CAR}, "Colombo roadside")
    assert inside[0].startswith("The place: this shot happens INSIDE the Family car (BMW 520d). The vehicle is the "
                                "place:")
    assert "The street is NOT a place of its own here: Colombo roadside is seen only through the windows" in inside[0]
    assert inside[0].endswith(vh.SEAT_RIGHT)
    at = vh.frame_lines([car.model_copy(update={"role": "at", "where": KERB})], {"car": CAR}, "Colombo roadside")
    assert at == [f"Vehicles in this shot: the Family car (BMW 520d) is {KERB}, all its wheels on the asphalt, the "
                  "same real vehicle as its vehicle plate."]
    assert vh.job("at") == ("ONLY the vehicle itself, exactly as shown: its make and model, body shape and colour, "
                            "wheels, lights and windows. Ignore everything around the vehicle in that picture (its "
                            "street, ground and light)")
    assert vh.job("inside") == vh.INSIDE_JOB and vh.WITH_INSIDE in vh.job("at", board=True)


def test_raphael_reads_the_vehicles_and_is_told_when_where_has_no_ground():
    scene = SceneS(blocks=[BlockS(index=1, kind="action", text="The family car stops at the kerb.")],
                   vehicles=[VehicleS(name="Family car", make="BMW 520d", look="silver sedan")],
                   empty=["the vending bay beside the shop"])
    text = listing(scene)
    assert "Vehicles: Family car (BMW 520d): silver sedan" in text and "Kept empty: the vending bay" in text
    assert "vehicles" not in scene_dump(SceneS(blocks=scene.blocks)), "a scene with none hashes as before"
    from tests.raphael import gold

    base = gold.stage1().by_id("c05")
    assert base is not None
    work = Bin(scene="1")
    work.clips = [base.model_copy(update={"id": "c01", "ir": {**(base.ir or {}), "vehicles": [
        {"name": "Family car (BMW 520d)", "role": "at", "where": "stopped at the kerb"},
        {"name": "A red bus", "role": "at", "where": "on the road"}]}})]
    codes = [f.code for f in vehicle_faults(scene, work)]
    assert codes == ["vehicle:name", "vehicle:where"]
    assert all(f.fix == "report" for f in vehicle_faults(scene, work)), "told, never blocking"



def test_a_job_reads_the_columns_vehicles_and_spots_are_found_by():
    """The live check of 2026-11-24: the job's canon select had no `class`, so no card read as a vehicle in a real job
    (the fixtures carry it, so every offline test passed)."""
    from hiru_ai.adapters.supabase_rest import CANON_FULL

    assert {"class", "parent_id"} <= set(CANON_FULL.split("current:")[0].strip(",").split(","))
