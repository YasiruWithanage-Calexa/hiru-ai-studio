"""plan/2026-11-25b: one prop roster per scene, each stand-in of a panel bound to its own sheet (lab/prop_mapping A).

The case is Love Hour scene 4 shots 11 and 1 on board v22, as `lab/prop_mapping/input/cases.json` saved it (the
writer's panel props and the mannequin colours) and the production's prop cards (their `details`), copied by hand:
no picture, no database."""
from __future__ import annotations

from contracts import props as P


def card(cid: str, name: str, details: str, aliases: tuple[str, ...] = ()) -> dict:
    return {"id": cid, "kind": "prop", "name": name, "aliases": list(aliases),
            "current": {"card": {"details": details}}}


CANON = [
    {"id": "anudi", "kind": "character", "name": "Anudi"},
    card("umbrella", "umbrella", "A navy folding umbrella with a short curved handle. Anudi carries it closed and "
         "opens it when the rain begins (scene 2); she holds it open over herself in the rain.", ("folding umbrella",)),
    card("phone", "phone", "iPhone 17 pro max - orange with transparent back cover. back view and front view. "),
    card("flask", "flask", "A scuffed two-litre stainless-steel vacuum flask with a dark-brown plastic handle, screw "
         "lid and narrow pouring spout; dull silver body with shallow dents."),
    card("bag", "bag", "A structured dark-brown leather document bag, approximately forty centimetres wide."),
    card("handbag", "handbag", "A medium tan faux-leather handbag with two short handles, a shoulder strap, "
         "brass-coloured fittings and an open exterior side pocket wide enough for a smartphone.", ("hand bag",)),
    card("cheque", "cheque", "A clean pale-blue rectangular bank cheque."),
]
COLOURS = {"Kasun": "red", "Anudi": "blue"}
LOOK = "tan handbag on the left forearm; navy folding umbrella"
CONDITION = "walking under an open umbrella in the first rain"
PLANS = ["Kasun hands Anudi her phone across the hatch. The tea flask stands on the serving ledge."]
SHOT_11 = [
    {"name": "phone", "held_by": "Anudi", "hand": "right", "rests_on": "", "frame_side": "right"},
    {"name": "umbrella", "held_by": "Anudi", "hand": "left", "rests_on": "", "frame_side": "right"},
    {"name": "handbag", "held_by": "Anudi", "hand": "", "rests_on": "Anudi's left forearm", "frame_side": "right"},
    {"name": "tea flask", "held_by": "", "hand": "", "frame_side": "left",
     "rests_on": "The rear/right end of the stainless-steel side serving ledge"},
]
SHOT_1 = [
    {"name": "phone", "held_by": "Kasun", "hand": "right", "rests_on": "", "frame_side": "centre"},
    *SHOT_11[1:],
]
LABELS = ["the face sheet for Kasun", "the face sheet for Anudi", "the look sheet for Kasun",
          "the look sheet for Anudi", "view 1 (wide) of the location sheet for Colombo roadside",
          "the vehicle plate for Food three-wheeler",
          "the reference sheet for phone", "the reference sheet for umbrella", "the reference sheet for handbag",
          "the approved scene board panel of this shot"]


def roster() -> list[P.RosterProp]:
    return P.scene_props(CANON, PLANS, things=["phone"], carried=[LOOK, CONDITION])


def test_the_roster_holds_what_she_carries_and_never_the_document_bag() -> None:
    got = {p.name: p.source for p in roster()}
    assert got == {"umbrella": "look", "phone": "prop", "flask": "prop", "handbag": "look"}
    assert "bag" not in got and "cheque" not in got


def test_a_stand_in_binds_against_the_roster_only() -> None:
    r = roster()
    assert P.resolve("bag", r).name == "handbag", "the document bag is not on this scene's roster"
    assert P.resolve("the clay tea flask", r).name == "flask", "by the last word"
    assert P.resolve("hand bag", r).name == "handbag", "an alias"
    assert P.resolve("kettle", r) is None
    others = P.canon_props(CANON)
    assert P.resolve("cheque", r) is None and P.resolve("the clay cheque", r, others).name == "cheque", "exact name"
    assert P.resolve("bag", r, others).name == "handbag", "the roster first"
    assert P.resolve("bag", [], others).name == "bag" and P.resolve("smartphone", [], others) is None, "never a suffix"
    with_bag = P.scene_props(CANON, ["He sets down his bag."], carried=[LOOK])
    assert P.resolve("bag", with_bag).name == "bag" and P.resolve("handbag", with_bag).name == "handbag"


def test_bind_keeps_every_stand_in_with_its_hand_side_and_state() -> None:
    bound = P.bind([*SHOT_11, {"name": "clay kettle", "held_by": "", "rests_on": "the bench"}], roster(), COLOURS,
                   texts=[CONDITION])
    got = {b.prop.name: b for b in bound.props}
    assert list(got) == ["phone", "umbrella", "handbag", "flask", "kettle"]
    assert got["umbrella"].state == "open" and got["umbrella"].colour == "blue" and got["umbrella"].hand == "left"
    assert got["kettle"].prop.source == "words" and got["kettle"].prop.canon_id == ""
    assert bound.canon_ids() == ["phone", "umbrella", "handbag", "flask"]
    palm = P.bind(SHOT_1, roster(), COLOURS, texts=["Near-side palm open beneath the clay phone, not yet gripping it.",
                                                    "An open hand under the phone."])
    assert palm.props[0].prop.name == "phone" and palm.props[0].state == "", "an open palm is not an open phone"
    twice = P.bind([SHOT_11[0], {**SHOT_11[0], "name": "the clay phone"}], roster(), COLOURS)
    assert len(twice.props) == 1


def test_where_words_from_the_writers_fields() -> None:
    bound = {b.prop.name: b for b in P.bind(SHOT_1, roster(), COLOURS).props}
    assert P.where_words(bound["phone"]) == ("the clay phone in Kasun's right hand (the red mannequin's), at the "
                                             "centre of the frame")
    assert P.where_words(bound["handbag"]) == "the clay handbag Anudi carries, on Anudi's left forearm, at frame right"
    assert P.where_words(bound["flask"]) == ("the clay tea flask resting on the rear/right end of the stainless-steel "
                                             "side serving ledge, at frame left")


def test_the_binding_paragraph_is_the_labs_words() -> None:
    bound = P.bind(SHOT_11, roster(), COLOURS, texts=[CONDITION])
    text = P.binding_text(bound, P.image_numbers(LABELS, bound), P.once_line(bound, {"Anudi": LOOK}))
    # the lab's head, tail and "each prop once" (`lab/prop_mapping/run.py` `roster_words`, approach A)
    assert text.startswith("The approved scene board panel shows the props as plain white clay stand-ins. White is "
                           "never a prop's colour: each stand-in marks only where a real prop is, its size, its angle "
                           "and the hand that holds it. These are the props, each exactly once: ")
    assert text.endswith("Keep the panel's layout, proportions and perspective for every prop; add no other prop. No "
                         "white clay shape, blank object or unfinished prop remains in the frame.")
    assert ("is the phone: paint it exactly as image 7 shows it (iPhone 17 pro max - orange with transparent back "
            "cover)") in text
    assert "is the umbrella: paint it exactly as image 8 shows it (a navy folding umbrella with a short curved " \
           "handle), open" in text
    assert "is the handbag: paint it exactly as image 9 shows it" in text
    assert "is the flask: it has no picture: paint a scuffed two-litre stainless-steel vacuum flask" in text
    assert ("Each prop appears once: the umbrella and the handbag on Anudi's look sheet are these same things, never a "
            "second umbrella or handbag.") in text
    assert "spout, dull silver" in text, "a ';' inside a look would read as the next prop"


def test_the_draft_says_draft_and_nobody_carrying_says_only_once() -> None:
    bound = P.bind(SHOT_11[:1], roster(), COLOURS)
    text = P.binding_text(bound, {"phone": 3}, P.once_line(bound, {"Kasun": "a wristwatch"}), subject=P.DRAFT)
    assert text.startswith("The approved draft shows the props") and "Keep the draft's layout" in text
    assert " Each prop appears once. Keep" in text


def test_image_numbers_read_the_attached_labels() -> None:
    bound = P.bind(SHOT_11, roster(), COLOURS)
    assert P.image_numbers(LABELS, bound) == {"phone": 7, "umbrella": 8, "handbag": 9}
    assert P.image_numbers(LABELS[:7], bound) == {"phone": 7}
    assert P.prop_looks(bound)["handbag"].startswith("a medium tan faux-leather handbag")
