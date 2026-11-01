"""A production with canon and an approved scene from the Harbour Lights fixture, shared by the
Phase 4 function tests (shot_producer, frame_render)."""
from __future__ import annotations

from uuid import uuid4

from contracts import sceneplan
from contracts.screenplay import parse_document
from contracts.shotplan import ProposedShot, fit
from tests.services.doc_ingest.conftest import CORPUS

PID = uuid4()
KAMALA, NIMAL, HOUSE = str(uuid4()), str(uuid4()), str(uuid4())

CANON = [
    {"id": KAMALA, "kind": "character", "code": "C01", "name": "Kamala", "aliases": ["Amma"], "locked": False,
     "current": {"version": 2, "card": {"gender": "female", "appearance": "52, grey-streaked hair in a bun"},
                 "wardrobe_anchor": "a faded blue cotton saree", "voice_pin": "low, clipped female voice (52)"}},
    {"id": NIMAL, "kind": "character", "code": "C02", "name": "Nimal", "aliases": [], "locked": False,
     "current": {"version": 1, "card": {"gender": "male"}, "wardrobe_anchor": "a creased white shirt",
                 "voice_pin": ""}},
    {"id": HOUSE, "kind": "location", "code": "L01", "name": "Kamala's house", "aliases": [], "locked": False,
     "current": {"version": 1, "card": {"look": "a small tiled-roof house with a smoky kitchen"},
                 "wardrobe_anchor": "", "voice_pin": ""}},
]


def fixture_scene(n: int = 0, *, status: str = "approved",
                  per_block: bool = True) -> tuple[dict, list[dict], list[dict]]:
    """A Harbour Lights scene → (scene row, line rows, shot rows), fitted by the real kernel."""
    doc = parse_document((CORPUS / "harbour-lights-ep01-script.fountain").read_text(encoding="utf-8"))
    parsed = doc.scenes[n]
    scene_id = str(uuid4())
    blocks, lines = [], []
    for b in parsed.blocks:
        if b.kind == "dialogue":
            lid = str(uuid4())
            lines.append({"id": lid, "production_id": str(PID), "scene_id": scene_id, "ord": len(lines),
                          "speaker": b.speaker.title(), "text": b.text, "delivery": b.delivery,
                          "character_id": {"NIMAL": NIMAL, "KAMALA": KAMALA}.get(b.speaker)})
            blocks.append({"kind": "dialogue", "text": "", "line_id": lid})
        else:
            blocks.append({"kind": b.kind, "text": b.text, "line_id": None})
    scene = {"id": scene_id, "production_id": str(PID), "episode_id": str(uuid4()), "number": n + 1,
             "heading": parsed.heading.raw, "time_of_day": "DAWN", "envelope_s": 60, "status": status,
             "script": blocks, "location_id": HOUSE, "episode": {"number": 1}}
    items = sceneplan.items_for(blocks, lines)
    proposal = ([ProposedShot(i, i + 1, "MCU" if items[i].is_line else "WIDE") for i in range(len(items))]
                # one shot over the whole scene, as a person kept it (locked): left to the kernel it would be cut
                if per_block else [ProposedShot(0, len(items), "WIDE", duration=8, duration_locked=True)])
    shots, line_rows, _ = sceneplan.rows_after_fit(scene, [{"start": p.start, "duration_locked": p.duration_locked}
                                                           for p in proposal],
                                                   fit(items, proposal, envelope_s=60), lines)
    for s in shots:
        s.update(ir={}, design={}, camera_overrides={})
    return scene, line_rows, shots


# ── the phone call (plan/2026-11-01): the shot that kept painting the caller into the frame ──

ANUDI, KASUN, FATHER, STALL = str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4())

PHONE_CANON = [
    {"id": KASUN, "kind": "character", "code": "C01", "name": "Kasun", "aliases": [], "locked": False,
     "current": {"version": 1, "card": {"gender": "male", "appearance": "late 20s, lean"},
                 "wardrobe_anchor": "a faded orange apron over a white T-shirt", "voice_pin": "warm young male voice"}},
    {"id": ANUDI, "kind": "character", "code": "C02", "name": "Anudi", "aliases": [], "locked": False,
     "current": {"version": 1, "card": {"gender": "female", "appearance": "mid 20s, long dark hair"},
                 "wardrobe_anchor": "a light olive blouse and off-white trousers", "voice_pin": "soft female voice"}},
    {"id": FATHER, "kind": "character", "code": "C03", "name": "Anudi's Father", "aliases": ["Father"],
     "locked": False,
     "current": {"version": 1, "card": {"gender": "male", "appearance": "a well-groomed businessman in his 50s"},
                 "wardrobe_anchor": "a navy polo shirt and formal trousers", "voice_pin": "firm older male voice"}},
    {"id": STALL, "kind": "location", "code": "L01", "name": "Kasun's Food Three-Wheeler", "aliases": [],
     "locked": False, "current": {"version": 1, "card": {"look": "a food three-wheeler under an umbrella"},
                                  "wardrobe_anchor": "", "voice_pin": ""}},
]

# (kind, text, speaker id, delivery). The father's delivery comes from `phone_scene(delivery=...)`.
# Shot 1: Kasun's line; shot 2: the smile, the ring, the father's call.
PHONE_SCRIPT = [
    ("action", "Kasun smiles.", None, ""),
    ("dialogue", "Started with Rs. 5,000. I'm trying to make it bigger.", KASUN, ""),
    ("action", "Anudi smiles back.", None, ""),
    ("action", "Suddenly, her phone rings.", None, ""),
    ("action", "It is her father.", None, ""),
    ("dialogue", "Anudi, where are you? Come home. We need to talk about your marriage.", FATHER, "on the phone"),
]


def phone_scene(*, delivery: str = "on the phone") -> tuple[dict, list[dict], list[dict]]:
    """Scene 2 of the Kasun / Anudi drama, cut as two shots: Kasun's line (MCU), then Anudi takes
    her father's call (MCU, voiceover). `delivery` = "" is the line as the old build left it."""
    scene_id = str(uuid4())
    names = {KASUN: "Kasun", ANUDI: "Anudi", FATHER: "Anudi's Father"}
    blocks, lines = [], []
    for kind, text, who, how in PHONE_SCRIPT:
        if kind == "dialogue":
            lid = str(uuid4())
            lines.append({"id": lid, "production_id": str(PID), "scene_id": scene_id, "ord": len(lines),
                          "speaker": names[who], "text": text, "delivery": delivery if who == FATHER else how,
                          "character_id": who})
            blocks.append({"kind": "dialogue", "text": "", "line_id": lid})
        else:
            blocks.append({"kind": kind, "text": text, "line_id": None})
    scene = {"id": scene_id, "production_id": str(PID), "episode_id": str(uuid4()), "number": 2,
             "heading": "EXT. KASUN'S FOOD THREE-WHEELER - DAY", "title": "Anudi And Kasun Exchange Smiles",
             "note": "", "time_of_day": "DAY", "envelope_s": 16, "status": "approved", "script_version": 1,
             "script": blocks, "location_id": STALL,
             "episode": {"number": 1, "title": "The Meeting",
                         "synopsis": "Anudi meets Kasun at his food stall; her father is arranging her marriage."}}
    items = sceneplan.items_for(blocks, lines)
    # The call shot is locked at 8 s: left to the kernel it would split (plan/2026-11-01b), and these
    # tests want the shot as a person (or an older build) kept it.
    proposal = [ProposedShot(0, 2, "MCU", "Kasun's start"),
                ProposedShot(2, 6, "MCU", "Anudi takes the call", duration=8, duration_locked=True)]
    shots, line_rows, _ = sceneplan.rows_after_fit(scene, [{"start": p.start} for p in proposal],
                                                   fit(items, proposal, envelope_s=16), lines)
    for s in shots:
        s.update(ir={}, design={}, camera_overrides={}, intent={})
    return scene, line_rows, shots
