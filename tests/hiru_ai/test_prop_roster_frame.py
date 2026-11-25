"""plan/2026-11-25b phases 3-4: a first frame painted from a board panel that lists its props takes the sheet of every
prop the panel shows and binds each stand-in to its image number (lab/prop_mapping A); its one hands sentence is the
board's. Rows in, words out: no picture, no model."""
from __future__ import annotations

import re
from typing import Any

from contracts import board as kit
from contracts import props as P
from contracts.frame_brief import MAX_REFERENCES, SetupFrame, missing_references, plan_references
from contracts.producer import BLOCKING_LABEL, DRAFT_LABEL
from hiru_ai.core import parts


def sheet(path: str) -> dict[str, Any]:
    return {"reference_assets": [{"path": path, "kind": "sheet"}]}


def prop(cid: str, name: str, details: str, path: str = "") -> dict[str, Any]:
    return {"id": cid, "code": cid.upper(), "kind": "prop", "name": name, "aliases": [],
            "current": {**(sheet(path) if path else {}), "card": {"details": details}}}


ANUDI = {"id": "anudi", "code": "C01", "kind": "character", "name": "Anudi",
         "current": {**sheet("p/anudi.png"), "card": {"gender": "female"}}}
CANON = [
    ANUDI,
    prop("phone", "phone", "iPhone 17 pro max - orange with transparent back cover. back view.", "p/phone.png"),
    prop("umbrella", "umbrella", "A navy folding umbrella with a short curved handle. Open in the rain.",
         "p/umbrella.png"),
    prop("handbag", "handbag", "A medium tan faux-leather handbag with two short handles.", "p/handbag.png"),
    prop("flask", "flask", "A scuffed two-litre stainless-steel vacuum flask."),
    prop("bag", "bag", "A structured dark-brown leather document bag.", "p/bag.png"),
]
PANEL_PROPS = [
    {"name": "phone", "held_by": "Anudi", "hand": "right", "rests_on": "", "frame_side": "right"},
    {"name": "umbrella", "held_by": "Anudi", "hand": "left", "rests_on": "", "frame_side": "right"},
    {"name": "bag", "held_by": "Anudi", "hand": "", "rests_on": "Anudi's left forearm", "frame_side": "right"},
    {"name": "tea flask", "held_by": "", "hand": "", "rests_on": "the serving ledge", "frame_side": "left"},
]
LOOK = {"id": "look-1", "entity_id": "anudi", "outfit": "a cream blouse", "accessories": "tan handbag; navy umbrella"}
# the ledger says Anudi holds the phone in one hand, the board puts it in her right: the shot 1 contradiction (F6)
SCENE = {"id": "sc4", "heading": "EXT. ROADSIDE - DAY",
         "script": [{"kind": "action", "text": "Anudi reads her phone."}],
         "staging": {"by": "stager", "basis": "", "zones": ["roadside"],
                     "marks": [{"block": 0, "who": "Anudi", "zone": "roadside", "holding": "phone"}]}}


def shot(**over: Any) -> dict[str, Any]:
    return {"id": "s11", "scene_id": "sc4", "number": 11, "framing": "TWO", "block_start": 0, "block_end": 0,
            "ir": {"setting": "A wet roadside.", "first_frame": {"subjects": ["Anudi under the open umbrella."]}},
            "intent": {"on_screen": ["anudi"], "heard_only": []}, "design": {}, **over}


def bound(props: list[dict[str, Any]] | None = None) -> P.Bound:
    roster = P.scene_props(CANON, ["Anudi reads her phone. A tea flask on the ledge."], ["phone"],
                           ["tan handbag; navy umbrella"])
    return P.bind(PANEL_PROPS if props is None else props, roster, {"Anudi": "blue"}, ["the open umbrella"])


# ── phase 3: the pictures ────────────────────────────────────────────────────────────────────────────────────


def test_every_prop_the_panel_shows_gets_its_sheet_and_the_document_bag_never():
    planned = plan_references(SCENE, shot(), CANON, ["anudi"], {}, faces=False, panel_props=bound())
    labels = [p.label for p in planned if p.choices]
    assert labels == ["the character sheet for Anudi", "the reference sheet for phone",
                      "the reference sheet for umbrella", "the reference sheet for handbag"]
    assert "No reference sheet for flask: it is painted from words only." in missing_references(planned)
    assert not any("bag" == p.name for p in planned), "'bag' on the panel is her handbag"


def test_without_a_panel_the_references_are_todays():
    today = plan_references(SCENE, shot(), CANON, ["anudi"], {}, faces=False)
    assert [p.label for p in today] == ["the character sheet for Anudi",
                                        "the reference sheet for phone (held by Anudi)"]
    assert plan_references(SCENE, shot(), CANON, ["anudi"], {}, faces=False, panel_props=P.Bound()) == today


def test_panel_props_sit_on_top_of_the_limit_up_to_four_and_before_the_same_setup_frame():
    many = CANON + [prop(f"x{i}", f"thing{i}", "A thing.", f"p/x{i}.png") for i in range(4)]
    rows = [{"name": f"thing{i}", "rests_on": "the ledge"} for i in range(4)] + PANEL_PROPS[:2]
    roster = P.scene_props(many, [" ".join(f"thing{i}" for i in range(4)) + " phone umbrella"])
    setup = SetupFrame(frame_id="f1", slate="4A-1", path="p/f1.png")
    planned = plan_references(SCENE, shot(), many, ["anudi"], {}, faces=False, setup=setup,
                              panel_props=P.bind(rows, roster))
    sheets = [p for p in planned if p.role == "prop"]
    assert len(sheets) == P.MAX_PANEL_PROPS and [p.name for p in sheets] == [f"thing{i}" for i in range(4)]
    assert planned[-1].role == "setup", "the same-setup frame still comes, after the props"
    assert len([p for p in planned if p.role != "prop"]) <= MAX_REFERENCES


def test_a_prop_a_person_took_out_of_the_shot_is_not_attached():
    planned = plan_references(SCENE, shot(person_edits={"cast": {"remove": ["umbrella"]}}), CANON, ["anudi"], {},
                              faces=False, panel_props=bound())
    assert "umbrella" not in [p.name for p in planned]


# ── phase 4: the words ───────────────────────────────────────────────────────────────────────────────────────


def world() -> Any:
    world_cls = parts.step("frame_compose", "logic").World
    return world_cls.of({"production": {"id": "p1", "orientation": "vertical"}, "canon": CANON, "scene": SCENE,
                         "lines": [], "looks": {"anudi": LOOK}, "shots": [shot()]})


def writer() -> kit.Writer:
    return kit.Writer.of({"world": "A wet grey morning.", "geography": "Across.", "conflicts": [], "panels": [{
        "shot": 11, "zone": "roadside", "camera": "Waist-up.", "background": "The stall at left.",
        "picture": "The blue mannequin holds the clay phone; the clay umbrella open above her.",
        "people": [{"name": "Anudi", "state": "", "left_hand": "grips the clay umbrella shaft",
                    "right_hand": "holds the clay phone at chest height"}],
        "props": PANEL_PROPS}]})


def panel() -> dict[str, Any]:
    p = writer().panels[0]
    return {"props": kit.panel_dump(p)["props"], "colours": {"Anudi": "blue"},
            "words": [p.picture, *(h for x in p.people for h in (x.left_hand, x.right_hand))]}


def brief(blocking: bool = True, with_panel: bool = True) -> tuple[str, list[str]]:
    w = world()
    s = shot()
    pictures = w.planned(s, panel() if with_panel else None)
    # the test scene stages nobody, so Anudi's look sheet is named here as the renderer would attach it
    labels = ["the look sheet for Anudi", *(x.label for x in pictures if x.choices),
              BLOCKING_LABEL if blocking else DRAFT_LABEL]
    board = kit.frame_sections(writer(), 11, {"Anudi": "blue"}, [], (), blocking=blocking)
    return w.brief(s, labels, board=board, panel=panel() if with_panel else None).text(), labels


def test_each_stand_in_is_bound_to_the_image_number_attached():
    text, labels = brief()
    assert P.PROPS_SLOT not in text and kit.PROP_STAND_INS not in text
    numbers = {re.sub(r"^the reference sheet for ", "", x): n for n, x in enumerate(labels, 1)
               if x.startswith("the reference sheet for ")}
    assert set(numbers) == {"phone", "umbrella", "handbag"}
    for name, n in numbers.items():
        assert f"is the {name}: paint it exactly as image {n} shows it" in text
        assert f"image {n}: {name} exactly as shown (" in text and "not its backdrop or light" in text
    assert ("the clay tea flask resting on the serving ledge, at frame left is the flask: it has no picture: paint a "
            "scuffed two-litre stainless-steel vacuum flask") in text, "a canon prop only the panel names, by its name"
    assert "the clay bag Anudi carries, on Anudi's left forearm, at frame right is the handbag" in text
    assert "is the umbrella: paint it exactly as image" in text and "), open;" in text
    assert ("Each prop appears once: the umbrella and the handbag on Anudi's look sheet are these same things, never "
            "a second umbrella or handbag.") in text
    assert text.count("The approved scene board panel shows the props as plain white clay stand-ins.") == 1


def test_the_boards_hands_are_the_only_hands_sentence():
    text, _ = brief()
    assert kit.HELD_HEAD in text
    assert "Hands: " not in text, "the ledger's sentence is left out while the board's is there"
    plain = world().brief(shot(), ["the character sheet for Anudi"]).text()
    assert "Hands: " in plain and kit.HELD_HEAD not in plain, "a frame with no panel keeps the ledger's hands"


def test_the_frame_check_is_told_the_boards_hands():
    board = kit.frame_sections(writer(), 11, {"Anudi": "blue"}, [], (), blocking=True)
    assert world().expected(shot(), board)["hands"].startswith(kit.HELD_HEAD)
    assert not world().expected(shot())["hands"].startswith(kit.HELD_HEAD)


def test_a_draft_panel_says_draft_and_an_unbound_slot_keeps_todays_rule():
    text, _ = brief(blocking=False)
    assert "The approved draft shows the props as plain white clay stand-ins. White is never" in text
    assert "Keep the draft's layout" in text
    bare, _ = brief(with_panel=False)
    assert kit.PROP_STAND_INS.replace("The approved draft", "The approved scene board panel") in bare
    assert P.PROPS_SLOT not in bare
