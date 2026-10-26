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
                if per_block else [ProposedShot(0, len(items), "WIDE")])
    shots, line_rows, _ = sceneplan.rows_after_fit(scene, [{"start": p.start} for p in proposal],
                                                   fit(items, proposal, envelope_s=60), lines)
    for s in shots:
        s.update(ir={}, design={}, camera_overrides={})
    return scene, line_rows, shots
