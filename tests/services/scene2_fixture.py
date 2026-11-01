"""Episode 1, Scene 2 of the Kasun / Anudi drama as stored on 2026-11-01 (plan/2026-11-01b): the
scene whose shot list showed too little. Block numbers match the plan: 9 and 10 are what Anudi
does, 11 the "it is her father" information, 12 the father's line, 13-18 the second half."""
from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from contracts import sceneplan
from contracts.shotplan import Item

SCENE_ID = str(uuid5(NAMESPACE_URL, "scene2/scene"))
KASUN, ANUDI, FATHER = (str(uuid5(NAMESPACE_URL, f"scene2/{n}")) for n in ("kasun", "anudi", "father"))
NAMES = {KASUN: "Kasun", ANUDI: "Anudi", FATHER: "Anudi's Father"}

# (kind, text, speaker id, delivery) in script order; index = block index.
SCRIPT: list[tuple[str, str, str | None, str]] = [
    ("action", "Kasun stirs a pot of rice behind his food three-wheeler.", None, ""),  # 0
    ("action", "Anudi walks up to the stall.", None, ""),  # 1 move
    ("dialogue", "Is this the place everyone talks about?", ANUDI, ""),  # 2
    ("dialogue", "Only if the rice is hot.", KASUN, ""),  # 3
    ("action", "Anudi laughs.", None, ""),  # 4
    ("dialogue", "Then give me a plate.", ANUDI, ""),  # 5
    ("dialogue", "You are the first customer today.", KASUN, ""),  # 6
    ("action", "Kasun slides a plate across the counter.", None, ""),  # 7
    ("dialogue", "Started with five thousand rupees. I am trying to make it bigger.", KASUN, ""),  # 8
    ("action", "Anudi smiled back.", None, ""),  # 9 act
    ("action", "Suddenly, her phone rang.", None, ""),  # 10 act
    ("action", "It is her father (voice only).", None, ""),  # 11 info
    ("dialogue", "Anudi, where are you? Come home. We need to talk about your marriage.", FATHER,
     "on the phone"),  # 12
    ("action", "Her smile disappeared.", None, ""),  # 13 act
    ("action", "She looked at Kasun one more time.", None, ""),  # 14 with_line
    ("dialogue", "I have to go.", ANUDI, ""),  # 15
    ("action", "She walked away.", None, ""),  # 16 move
    ("action", "Kasun watched her go.", None, ""),  # 17 act
    ("action", "He has no idea that this meeting is about to change his life.", None, ""),  # 18 inner
]

# What the classifier should read each action as (plan Phase 2); used to set up kernel tests.
SCREENS = {0: "act", 1: "move", 4: "with_line", 7: "act", 9: "act", 10: "act", 11: "info", 13: "act",
           14: "with_line", 16: "move", 17: "act", 18: "inner"}


def lines() -> list[dict]:
    out = []
    for kind, text, who, delivery in SCRIPT:
        if kind == "dialogue":
            assert who
            out.append({"id": f"l{len(out)}", "production_id": "p", "scene_id": SCENE_ID, "ord": len(out),
                        "speaker": NAMES[who], "text": text, "delivery": delivery, "character_id": who})
    return out


def blocks(*, screens: bool = False) -> list[dict]:
    """The scene's script as stored (`scenes.script`); with `screens`, as the classifier left it."""
    rows, n = [], 0
    for i, (kind, text, _, _) in enumerate(SCRIPT):
        if kind == "dialogue":
            rows.append({"kind": "dialogue", "text": "", "line_id": f"l{n}"})
            n += 1
        else:
            row = {"kind": kind, "text": text, "line_id": None}
            if screens:
                row |= {"screen": SCREENS[i], "events": 1, "by": "rules", "for_version": 1}
            rows.append(row)
    return rows


def items(*, screens: bool = True) -> list[Item]:
    return sceneplan.items_for(blocks(screens=screens), lines())


def scene_row(**extra) -> dict:
    return {"id": SCENE_ID, "production_id": "p", "episode_id": "e", "number": 2, "heading": "EXT. STALL - DAY",
            "title": "Anudi And Kasun Exchange Smiles", "note": "", "time_of_day": "DAY", "envelope_s": 35,
            "status": "split", "script_version": 1, "script": blocks(screens=True), "location_id": None,
            "episode": {"number": 1, "title": "The Meeting", "synopsis": ""}, **extra}
