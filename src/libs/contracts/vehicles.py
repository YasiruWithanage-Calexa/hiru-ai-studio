"""Vehicles: a role in each shot, never clay, always their own plate (plan/2026-11-24b; lab/vehicle_role,
lab/final_views).

A vehicle is a canon place of class `vehicle` (Love Hour's "Food three-wheeler", "Family car"). Each shot says which
vehicles it shows and the ROLE each plays (the role changes inside one scene: scene 2's car is the place of shot 1 and
stands at the kerb in shots 2-5):

    inside   the vehicle IS the place of this shot (people sit in or on it, the camera is in or on it)
    at       the vehicle stands in the scene's place; `where` says where, which way it faces and what it stands on

    shot.ir.vehicles              [{id, name, role, where}]: written by Raphael (by name; code maps names to ids)
    shot.person_edits.vehicles    [{id, role, where}]: a person's change, which wins (role "none" takes it out)
    older shots (no ir.vehicles)  a vehicle card named in the shot's words is `at`, `where` empty; never `inside`

The words are the labs' (`lab/vehicle_role/run.py`, `run_bmw.py`, `lab/final_views/run.py`); changes are listed in
plan/2026-11-24b/IMPLEMENTED.md. Pure: rows in, words out.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts.holding import names_place, picture_text

Role = Literal["inside", "at"]
ROLES: tuple[str, ...] = ("inside", "at")
VEHICLE_CLASS = "vehicle"
PLATE_HEAD = "the vehicle plate for "
SHEET_HEAD = "the vehicle sheet for "


class ShotVehicle(BaseModel):
    """One vehicle in one shot, as the board and the frame read it."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    make: str = ""
    role: Role = "at"
    where: str = ""


class VehicleEdit(BaseModel):
    """A person's change to one vehicle of a shot (`PersonEdits.vehicles`): its role ("none" takes it out) and where."""

    model_config = ConfigDict(extra="ignore")

    id: str
    role: Literal["inside", "at", "none"] = "at"
    where: str = Field(default="", max_length=400)


# ── the card ────────────────────────────────────────────────────────────────────────────────────────────────


def is_vehicle(row: Mapping[str, Any] | None) -> bool:
    return bool(row) and (row or {}).get("kind") == "location" and (row or {}).get("class") == VEHICLE_CLASS


def card_of(row: Mapping[str, Any]) -> Mapping[str, Any]:
    return ((row.get("current") or {}).get("card") or {}) if isinstance(row.get("current"), Mapping) else {}


def make_of(row: Mapping[str, Any]) -> str:
    """The vehicle's make ("BMW 520d, 2019, pearl silver"), "" when the card has none."""
    return " ".join(str(card_of(row).get("make") or "").split())


def named(name: str, make: str) -> str:
    """How a vehicle is named to a model (§2.1): "Family car (BMW 520d, 2019, pearl silver)"."""
    return f"{name} ({make})" if make else name


def plate_label(name: str, make: str = "") -> str:
    return f"{PLATE_HEAD}{named(name, make)}"


def sheet_label(name: str, make: str = "") -> str:
    """How the board names a vehicle's views sheet (lab/final_views `board_prompt`)."""
    return f"{SHEET_HEAD}{named(name, make)}: six named views of the one vehicle"


def vehicle_cards(canon: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [c for c in canon if is_vehicle(c)]


# ── a shot's vehicles ───────────────────────────────────────────────────────────────────────────────────────────


def _key(text: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", text.casefold()).split())


def match_card(name: str, canon: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The vehicle card a model named ("Family car", an alias, the name with its make in brackets), or None."""
    want = _key(re.sub(r"\s*\(.*\)\s*$", "", name))
    for row in vehicle_cards(canon):
        names = [str(row.get("name") or ""), *(str(a) for a in row.get("aliases") or [])]
        if want and any(_key(n) == want for n in names if n):
            return row
    return None


def from_wire(raw: Any, canon: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Raphael's `vehicles` of one clip (`[{name, role, where}]`) as stored on the shot: by id, a name that is no
    vehicle card dropped, each vehicle once, at most one `inside` (a second one is dropped)."""
    out: list[dict[str, str]] = []
    inside = False
    for v in raw if isinstance(raw, list) else []:
        if not isinstance(v, Mapping):
            continue
        row = match_card(str(v.get("name") or ""), canon)
        role = str(v.get("role") or "at")
        if row is None or role not in ROLES or any(o["id"] == str(row["id"]) for o in out):
            continue
        if role == "inside":
            if inside:
                continue
            inside = True
        out.append({"id": str(row["id"]), "name": str(row["name"]), "role": role,
                    "where": " ".join(str(v.get("where") or "").split())})
    return out


def shot_vehicles(shot: Mapping[str, Any], canon: Sequence[Mapping[str, Any]],
                  edits: Sequence[VehicleEdit] = ()) -> list[ShotVehicle]:
    """The vehicles a shot shows and the role of each (§2.2): its `ir.vehicles`, else (an older shot) every vehicle card
    named in its words as `at`; then a person's edits (`PersonEdits.vehicles`), which win. At most one `inside`."""
    by_id = {str(c["id"]): c for c in vehicle_cards(canon)}
    raw = shot.get("ir")
    ir: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    base: list[dict[str, str]] = []
    if isinstance(ir.get("vehicles"), list):
        base = [{"id": str(v.get("id") or ""), "role": str(v.get("role") or "at"), "where": str(v.get("where") or "")}
                for v in ir["vehicles"] if isinstance(v, Mapping)]
    else:  # an older shot: today's name finding, never inside
        words = picture_text(ir)
        base = [{"id": cid, "role": "at", "where": ""} for cid, row in by_id.items()
                if any(names_place(n, words) for n in (str(row.get("name") or ""),
                                                        *(str(a) for a in row.get("aliases") or [])) if n)]
    mine = {e.id: e for e in edits}
    rows = [dict(v, **({"role": mine[v["id"]].role, "where": mine[v["id"]].where or v["where"]}
                       if v["id"] in mine else {})) for v in base]
    rows += [{"id": e.id, "role": e.role, "where": e.where} for e in edits if e.id not in {v["id"] for v in base}]
    out: list[ShotVehicle] = []
    inside = False
    for v in rows:
        row = by_id.get(v["id"])
        if row is None or v["role"] not in ROLES or any(o.id == v["id"] for o in out):
            continue
        if v["role"] == "inside":
            if inside:
                continue
            inside = True
        out.append(ShotVehicle(id=v["id"], name=str(row.get("name") or ""), make=make_of(row),
                               role=v["role"], where=" ".join(v["where"].split())))  # type: ignore[arg-type]
    return out


def inside_of(vehicles: Sequence[ShotVehicle]) -> ShotVehicle | None:
    return next((v for v in vehicles if v.role == "inside"), None)


# ── where it stands (§2.2; lab/final_views fault 2: the car straddled the kerb drain) ───────────────────────────────

_SURFACES = (r"road|asphalt|tarmac|kerb\s*side|kerbside|curb\s*side|street|lane|bay|drive(?:way)?|ground|floor|sand|"
             r"gravel|concrete|pavement|verge|grass|dirt|mud|earth|yard|car\s*park|parking|tiles|forecourt|jetty|deck|"
             r"track|path|shoulder")
_ON = re.compile(rf"(?<![\w-])(?:on|onto)\s+((?:(?!(?:beside|by|near|at|in|with|and|of|to)\b)[\w'-]+\s+){{0,3}}"
                 rf"(?:{_SURFACES}))\b", re.IGNORECASE)
_SURFACE = re.compile(rf"\b((?:[a-z-]+\s+)?(?:{_SURFACES}))\b", re.IGNORECASE)


def surface_of(where: str) -> str:
    """What a vehicle's `where` says it stands on: the first surface after "on" ("its wheels on the bay's concrete" →
    "the bay's concrete"), else the first surface it names ("in the vending bay" → "the vending bay"); "" when it
    names none."""
    m = _ON.search(where or "") or _SURFACE.search(where or "")
    if m is None:
        return ""
    words = " ".join(m.group(1).lower().split())
    return "the " + re.sub(r"^(?:the|its|a|an)\s+", "", words)


def where_findings(vehicles: Iterable[Mapping[str, Any]]) -> list[str]:
    """An `at` vehicle whose `where` names no surface (road, asphalt, bay, ground ...): what the writer is told."""
    return [f"{v.get('name') or 'A vehicle'}: say what it stands on (the road, the asphalt, the bay's concrete, the "
            "ground) in `where`, so all its wheels stand on it."
            for v in vehicles if str(v.get("role") or "at") == "at" and not surface_of(str(v.get("where") or ""))]


# ── seat sides (§2.3; lab/final_views fault 4: the right-hand-drive driver came out at frame right) ────────────────

_CAR = re.compile(r"\b(car|sedan|saloon|hatchback|estate|suv|jeep|van|minivan|bus|lorry|truck|pickup|taxi|cab|"
                  r"steering wheel|bmw|toyota|nissan|honda|suzuki|mercedes|audi)\b", re.IGNORECASE)
_NOT_CAR = re.compile(r"\b(three-wheeler|tuk|tuk-tuk|auto-rickshaw|motorbike|motorcycle|scooter|bicycle|boat)\b",
                      re.IGNORECASE)
_LEFT_HAND = re.compile(r"\bleft[- ]hand[- ]drive\b|\bLHD\b", re.IGNORECASE)
SEAT_RIGHT = ("The driver's seat is on the car's RIGHT (right-hand drive): with the camera looking BACK from the "
              "front, the driver is at frame LEFT; looking FORWARD from the rear, at frame RIGHT.")
SEAT_LEFT = ("The driver's seat is on the car's LEFT (left-hand drive): with the camera looking BACK from the front, "
             "the driver is at frame RIGHT; looking FORWARD from the rear, at frame LEFT.")


def seat_sentence(row: Mapping[str, Any]) -> str:
    """The seat-side sentence for a car with a driving seat; right-hand drive (the Sri Lankan market) unless the card's
    make or look says left-hand drive. "" for a three-wheeler, a motorbike or a boat."""
    words = " ".join([str(row.get("name") or ""), make_of(row), str(card_of(row).get("look") or "")])
    if _NOT_CAR.search(words) or not _CAR.search(words):
        return ""
    return SEAT_LEFT if _LEFT_HAND.search(words) else SEAT_RIGHT


# ── the words (the labs') ───────────────────────────────────────────────────────────────────────────────────────

# lab/final_views `VEHICLE_JOB` (lab/vehicle_role `CAR_JOB` / `TUK_JOB` with the card's own words left out)
VEHICLE_JOB = ("ONLY the vehicle itself, exactly as shown: its make and model, body shape and colour, wheels, lights "
               "and windows{inside}. Ignore everything around the vehicle in that picture (its street, ground and "
               "light)")
WITH_INSIDE = ", and its inside: its dashboard, steering and seats"
# lab/final_views shot 1 (the vehicle's inside view is the place) and run_bmw `FRAME` ("the car this shot happens in")
INSIDE_JOB = ("the vehicle this shot happens in, its inside exactly as shown: its seats, door panels, dashboard and "
              "steering; ignore its light")
# lab/vehicle_role `CLAY_NEW`
CLAY_NEW = ("A vehicle is never a clay stand-in: every vehicle is painted real, exactly as its vehicle plate shows "
            "it, with its real colours.")


def job(role: str, board: bool = False) -> str:
    """What the image model takes from a vehicle's picture: the vehicle-only job (with its inside on a board, whose
    panels may be inside it), or, for the vehicle a shot happens INSIDE, its inside as the place."""
    if role == "inside" and not board:
        return INSIDE_JOB
    return VEHICLE_JOB.format(inside=WITH_INSIDE if board else "")


def wheels(where: str) -> str:
    """", all its wheels on the asphalt" (§2.2: the line always ends with what it stands on)."""
    return f", all its wheels on {surface_of(where) or 'the ground'}"


def board_line(panels: Sequence[tuple[int, Sequence[ShotVehicle]]], images: Mapping[str, int],
               cards: Mapping[str, Mapping[str, Any]]) -> str:
    """The board's "Vehicles (every panel):" line (lab run_bmw `VEHICLES`, final_views): which picture is which
    vehicle, then panel by panel each vehicle's role. `panels`: (the panel's number on this sheet, its vehicles);
    `images`: vehicle id → its picture's number; `cards`: vehicle id → its canon row (for the seat sides). "" when no
    panel has a vehicle."""
    shown = list(dict.fromkeys(v.id for _, vs in panels for v in vs))
    if not shown:
        return ""
    names = {v.id: v for _, vs in panels for v in vs}
    which = "; ".join(f"the {named(names[i].name, names[i].make)} is image {images[i]}" if i in images
                      else f"the {named(names[i].name, names[i].make)} has no picture" for i in shown)
    rows = []
    for n, vs in panels:
        for v in vs:
            if v.role == "inside":
                seat = seat_sentence(cards.get(v.id) or {})
                pic = f" exactly as image {images[v.id]} shows it" if v.id in images else ""
                rows.append(f"PANEL {n} is INSIDE the {v.name}: the vehicle is the place, its inside{pic}; the street "
                            "is seen only through the windows." + (f" {seat}" if seat else ""))
            else:
                where = v.where.rstrip(".") or "in the place, where the panel puts it"
                rows.append(f"PANEL {n}: the {v.name} is {where}{wheels(v.where)}, the same vehicle as "
                            + (f"image {images[v.id]}." if v.id in images else "its card says."))
    return ("Vehicles (every panel): every vehicle is real, never clay, exactly as its vehicle plate shows it: "
            f"{which}. Where each one is, panel by panel: " + " ".join(rows))


def frame_lines(vehicles: Sequence[ShotVehicle], cards: Mapping[str, Mapping[str, Any]], place: str) -> list[str]:
    """The frame's place words for its vehicles (§2.4; lab run_bmw `FRAME`, vehicle_role `FRAME_VEHICLES`): the place
    sentence of a shot INSIDE a vehicle (with the seat sides), then a line for the vehicles that stand in the place."""
    out: list[str] = []
    inside = inside_of(vehicles)
    if inside is not None:
        seat = seat_sentence(cards.get(inside.id) or {})
        street = f"{place} is" if place else "the world outside is"
        out.append(f"The place: this shot happens INSIDE the {named(inside.name, inside.make)}. The vehicle is the "
                   "place: its seats, door panels, dashboard and steering, exactly as its vehicle picture shows its "
                   f"inside. The street is NOT a place of its own here: {street} seen only through the windows, "
                   "softly out of focus." + (f" {seat}" if seat else ""))
    at = [v for v in vehicles if v.role == "at"]
    if at:
        out.append("Vehicles in this shot: " + "; ".join(
            f"the {named(v.name, v.make)} is {v.where.rstrip('.') or 'in the place'}{wheels(v.where)}, the same real "
            "vehicle as its vehicle plate" for v in at) + ".")
    return out


def prompter_facts(vehicles: Sequence[ShotVehicle]) -> list[str]:
    """The shot prompter's `vehicles` facts (§2.4): one line per vehicle, so its words and the pictures agree."""
    return [f"{named(v.name, v.make)}: INSIDE it (the vehicle is the place)" if v.role == "inside" else
            f"{named(v.name, v.make)}: at {v.where.rstrip('.') or 'the place'}{wheels(v.where)}" for v in vehicles]
