"""A small story written into the LAB COPY of the "test" production (2026-11-13), so production awareness and conflict
warnings can be tested. The database is never touched: `input/test_production.json` (the read-only export) in,
`input/story_production.json` out. Deterministic: the same input gives the same file.

The "test" production is a traffic seed: twelve scenes with the same filler. The story (Dilini, 21, is Nimal and
Kumari's daughter; Sahan her friend from the village tea shop):

    E1S2  tea shop   Dilini shows Sahan her acceptance letter from the Colombo Medical Faculty.
    E1S3  verandah   Nimal reads Dilini's medical faculty letter to Kumari; he pins it to the verandah wall.
    E2S2  tea shop   (the OPEN scene of the tests) Dilini packs her anatomy textbooks into a cloth bag.
    E2S4  tea shop   Sahan gives Dilini a stethoscope wrapped in newspaper.
    E3S2  tea shop   Dilini, back for a weekend, shows Sahan her first-week timetable from the medical faculty.

    python lab/sable_rows/story.py
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "input" / "test_production.json"
OUT = HERE / "input" / "story_production.json"

SYNOPSIS = {
    1: "Dilini is accepted to the Colombo Medical Faculty; Nimal is proud, Kumari worries about the cost.",
    2: "Dilini gets ready to leave the village for medical school; Sahan does not want her to go.",
    3: "Dilini's first weeks at medical school; she comes home for a weekend.",
}
# (episode, scene) → (the first action block, the last action block)
ACTIONS = {
    (1, 2): ("Dilini shows Sahan her acceptance letter from the Colombo Medical Faculty.",
             "They look at each other in silence."),
    (1, 3): ("Nimal reads Dilini's medical faculty letter aloud to Kumari.",
             "Nimal pins the letter to the verandah wall."),
    (2, 2): ("Dilini packs her anatomy textbooks into a cloth bag.", "They look at each other in silence."),
    (2, 4): ("Sahan gives Dilini a stethoscope wrapped in newspaper.", "Dilini holds it without a word."),
    (3, 2): ("Dilini, home for a weekend, shows Sahan her first-week timetable from the medical faculty.",
             "They look at each other in silence."),
}
CARDS = {
    "Dilini": "Nimal and Kumari's daughter, 21. Accepted to the Colombo Medical Faculty (E1S2); leaves the village "
              "for medical school in episode 2. Wears a saree.",
    "Kumari": "Dilini's mother, 48. Worries about paying for medical school.",
    "Nimal": "Dilini's father, 52. Proud of her place at the medical faculty.",
    "Sahan": "Dilini's friend from the village tea shop, 24. Does not want her to leave.",
}


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    out = copy.deepcopy(data)
    numbers = {e["id"]: e["number"] for e in out["episodes"]}
    for e in out["episodes"]:
        e["title"] = f"Episode {e['number']}"
        e["synopsis"] = SYNOPSIS[e["number"]]
    for s in out["scenes"]:
        key = (numbers[s["episode_id"]], s["number"])
        if key in ACTIONS:
            first, last = ACTIONS[key]
            actions = [i for i, b in enumerate(s["script"]) if b.get("kind") != "dialogue"]
            s["script"][actions[0]]["text"] = first
            s["script"][actions[-1]]["text"] = last
    for c in out["canon"]:
        if c["name"] in CARDS and isinstance(c.get("card"), dict):
            c["card"] = {**c["card"], "summary": CARDS[c["name"]]}
    out["production"]["title"] = "test (lab story)"
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"{OUT.name}: the story written into {len(ACTIONS)} scenes, {len(CARDS)} cards, 3 synopses")


if __name__ == "__main__":
    main()
