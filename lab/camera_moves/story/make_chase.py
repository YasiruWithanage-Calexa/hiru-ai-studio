"""A test scene written for the camera_moves lab (2026-11-20, the person's yes): a CHASE, with a rooftop hide and a
reveal, in Ekama's world (Dinu, Mudalali's man), written as a scene packet in the reader's shape so the product's
Raphael plans it like any other scene. Built from Ekama E01-S03's packet (series direction, the packet's form); every
story field is replaced. Nothing is written to the database.

    python lab/camera_moves/story/make_chase.py      writes story/chase_packet.json  {"E09-S01": packet}
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SRC = ROOT / "lab/two_memories/runs/pipeline_ekama_run2/09_packets.json"
SID = "E09-S01"


def block(n: int, kind: str, text: str, intent: str, delivery: str, events: list[dict], speaker: str = "",
          addressee: str = "", heard_by: list[str] | None = None) -> dict:
    bid = f"{SID}-B{n:02d}"
    return {"id": bid, "kind": kind, "text": text, "speaker": speaker, "presence": "on_screen", "device": "",
            "addressee": addressee, "heard_by": heard_by or [], "intent": intent, "delivery_hint": delivery,
            "intent_source": "script",
            "events": [{"id": f"{bid}-e{i + 1}", **e} for i, e in enumerate(events)]}


def ev(actors: list[str], things: list[str], spot: str, change: str, function: str, speech: bool = False) -> dict:
    return {"actors": actors, "things": things, "spot": spot, "speech": speech, "visible": True, "change": change,
            "function": function}


def main() -> None:
    base = json.loads(SRC.read_text(encoding="utf-8"))["E01-S03"]
    p = copy.deepcopy(base)
    p["ids"] = {"C01": {"name": "Dinu", "kind": "person"}, "C09": {"name": "Rohan", "kind": "person"},
                "L10": {"name": "Pettah market", "kind": "place"}, "L11": {"name": "narrow alley", "kind": "place"},
                "L12": {"name": "rooftop", "kind": "place"}, "P03": {"name": "metal box", "kind": "thing"},
                "P06": {"name": "torch", "kind": "thing"}, "P07": {"name": "fruit cart", "kind": "thing"}}
    a = p["A_scene"]
    a.update({
        "id": SID, "heading": "SCENE 01 - EXT. PETTAH MARKET AND ROOFTOP - COLOMBO - NIGHT - 1.25 MINUTES",
        "title": "The market chase",
        "summary": "Rohan spots Dinu carrying Nimal's metal box through the night market and chases him through the "
                   "crowd, an alley and up to a rooftop, where Dinu hides from the torch and finds the box empty.",
        "purpose": "Put Dinu in physical danger for the box, then turn the escape into a new mystery: the box is "
                   "empty.",
        "purpose_source": "script",
        "before_on_page": {"empty": "first scene"}, "after_on_page": {"empty": "last scene"},
        "time": {"story_order": 1, "story_day": {"empty": "not stated"}, "relative": "Night, after Nimal's death",
                 "kind": "linear", "anchor": "", "source": "script"},
        "before_in_story": {"empty": "not stated"}, "after_in_story": {"empty": "not stated"},
        "threads": [], "irony": {"empty": "none stated"},
        "knowledge": [{"person": "Dinu", "learns": "The metal box is empty.", "audience_only": False,
                       "source": "script"}],
        "looks": [],
        "relationships": [{"between": ["Dinu", "Rohan"], "state": "Rohan hunts Dinu for Mudalali.", "scene": SID,
                           "source": "script"}],
    })
    p["B_people"] = [
        {"id": "C01", "name": "Dinu", "kind": "person", "place_kind": None,
         "card": {"summary": {"value": "Dinu - 32, cash-van driver, Nimal's closest friend.", "source": "script"}},
         "presence": "on_screen", "wants": "Escape with the box and learn what Nimal left him.",
         "feeling_start": "Watchful", "feeling_end": "Breathless and lost", "source": "script"},
        {"id": "C09", "name": "Rohan", "kind": "person", "place_kind": None,
         "card": {"summary": {"value": "Rohan - 40, Mudalali's enforcer, black raincoat, heavy build.",
                              "source": "script"}},
         "presence": "on_screen", "wants": "Catch Dinu and take the box.", "feeling_start": "Predatory",
         "feeling_end": "Thwarted", "source": "script"},
    ]
    p["C_place"] = {"id": "L10", "name": "Pettah market", "kind": "place", "place_kind": "set",
                    "card": {"summary": {"value": "A crowded night market lane in Pettah, Colombo: stalls under "
                                                  "tarpaulins, sodium light, rain on the road; a narrow alley and an "
                                                  "iron stairway up to a flat rooftop with water tanks.",
                                         "source": "script"}}}
    p["D_things"] = [
        {"id": "P03", "name": "metal box", "kind": "thing", "place_kind": None,
         "card": {"summary": {"value": "A small dented metal box.", "source": "script"}}, "role": "used",
         "holder_start": "Dinu", "holder_end": "Dinu", "source": "script"},
        {"id": "P06", "name": "torch", "kind": "thing", "place_kind": None,
         "card": {"summary": {"value": "A heavy black torch.", "source": "script"}}, "role": "used",
         "holder_start": "Rohan", "holder_end": "Rohan", "source": "script"},
        {"id": "P07", "name": "fruit cart", "kind": "thing", "place_kind": None,
         "card": {"summary": {"value": "A wooden cart piled with oranges.", "source": "script"}}, "role": "used",
         "holder_start": "", "holder_end": "", "source": "script"},
    ]
    p["E_blocks"] = [
        block(1, "action", "Rain over Pettah market at night. Dinu pushes through the crowded lane, a metal box "
                           "hidden under his jacket. Across the lane, Rohan, in a black raincoat, sees him.",
              "Establish the crowd, the box and the hunter before either moves.",
              "Let the recognition land on Rohan's face before anyone runs.",
              [ev(["C01"], ["P03"], "L10", "Dinu moves through the crowd with the hidden box.", "setup"),
               ev(["C09", "C01"], [], "L10", "Rohan recognises Dinu.", "reveal")]),
        block(2, "dialogue", "Dinu! Nawathipan!", "Name him and stop him in public.",
              "Shouted across the lane, cutting through the rain.",
              [ev(["C09"], [], "L10", "Rohan calls out to Dinu.", "escalation", True)],
              speaker="C09", addressee="C01", heard_by=["C01", "C09"]),
        block(3, "action", "Dinu runs. He shoves past shoppers and knocks over a fruit cart; oranges roll across the "
                           "wet road. Rohan chases him through the crowd.",
              "Start the pursuit with physical chaos.", "Fast and scrambling, never balletic.",
              [ev(["C01"], ["P07"], "L10", "Dinu flees and overturns the fruit cart.", "escalation"),
               ev(["C09"], [], "L10", "Rohan pursues.", "escalation")]),
        block(4, "action", "Dinu turns into a narrow alley, slips on the wet stones, recovers, and climbs an iron "
                           "stairway to a rooftop. Rohan is close behind.",
              "Tighten the space and the danger.", "Breathless; the slip is the closest call.",
              [ev(["C01"], ["P03"], "L11", "Dinu slips, recovers and climbs.", "escalation"),
               ev(["C09"], [], "L11", "Rohan follows into the alley.", "escalation")]),
        block(5, "action", "On the roof, Dinu hides behind a water tank, breathing hard. Rohan's torch beam sweeps "
                           "across the tank, stops, then moves on. His footsteps fade.",
              "Hold the danger in stillness until it passes.", "Silence and breath; the torch is the threat.",
              [ev(["C01"], ["P03"], "L12", "Dinu hides behind the water tank.", "turn"),
               ev(["C09"], ["P06"], "L12", "The torch beam searches, then moves away.", "turn")]),
        block(6, "action", "Dinu opens the metal box. It is empty.",
              "Turn the escape into loss and a new mystery.", "A held beat; the emptiness must read.",
              [ev(["C01"], ["P03"], "L12", "The box is revealed to be empty.", "reveal")]),
        block(7, "dialogue", "Nimal... eka koheda thiyanne?", "Voice the question the scene leaves.",
              "Whispered to himself, breathless.",
              [ev(["C01"], [], "L12", "Dinu asks where the thing is.", "texture", True)],
              speaker="C01", addressee="", heard_by=["C01"]),
    ]
    p["F_feeling"] = {"mood": ["urgent", "tense", "desperate"],
                      "turns": [f"{SID}-B03", f"{SID}-B05", f"{SID}-B06"]}
    p["H_length"] = {"stated_seconds": 75.0, "spoken_seconds": 3.0}
    p["I_open"] = {"empty": "no open question"}
    p["stage"] = {
        "zones": ["market lane", "narrow alley", "iron stairway", "rooftop"], "not_placed": {},
        "people": {"C01": {"in": {"zone": "market lane", "holding": "metal box", "posture": "walking"},
                           "out": {"zone": "rooftop", "holding": "metal box", "posture": "crouching"}},
                   "C09": {"in": {"zone": "market lane", "posture": "standing"},
                           "out": {"zone": "rooftop", "holding": "torch", "posture": "walking"}}},
        "changes_at": {
            f"{SID}-B01": [{"person": "Dinu", "zone": "market lane", "holding": "metal box", "posture": "walking"},
                           {"person": "Rohan", "zone": "market lane", "posture": "standing"}],
            f"{SID}-B03": [{"person": "Dinu", "zone": "market lane", "holding": "metal box", "posture": "running"},
                           {"person": "Rohan", "zone": "market lane", "posture": "running"}],
            f"{SID}-B04": [{"person": "Dinu", "zone": "iron stairway", "holding": "metal box", "posture": "climbing"},
                           {"person": "Rohan", "zone": "narrow alley", "posture": "running"}],
            f"{SID}-B05": [{"person": "Dinu", "zone": "rooftop", "holding": "metal box", "posture": "crouching"},
                           {"person": "Rohan", "zone": "rooftop", "holding": "torch", "posture": "walking"}],
        },
    }
    p.pop("J_series", None)
    (HERE / "chase_packet.json").write_text(json.dumps({SID: p}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {HERE / 'chase_packet.json'}: {len(p['E_blocks'])} blocks")


if __name__ == "__main__":
    main()
