"""Who holds what reaches the frame (contracts.holding, the Jonathan write step, the frame prompt and its check).

Replays Episode 1 scene 2, "Kasun Returns Anudi's Phone", as Shot Planner Jonathan planned it on 2026-11-06: the
script, the staging marks it wrote (with their gaps) and the shots the frames went wrong on. In those frames Anudi
was on a call before she had her phone back (S07), Kasun held her umbrella (S08), Kasun was on a call (S11), both
her hands were on the phone with the umbrella held up by nothing (S14), and Kasun crouched beside her as the phone
fell (S05). No model is called.
"""
from __future__ import annotations

from typing import Any

import pytest

from contracts import holding
from contracts.holding import Ledger, canon_match, names_place, shot_hands, state_in, thing_of, things_of
from contracts.jonathan.checks import _holding
from contracts.jonathan.scene import BlockS, SceneS
from contracts.jonathan.wire import JonathanWire, StagingW
from contracts.producer import default_camera, frame_prompt
from contracts.shotplan import Item
from contracts.staging import ShotIntent, staging
from hiru_ai.core import parts

write = parts.step("jonathan_write", "logic")

SCRIPT = [
    "Anudi steps out of a comfortable family car.", "She is dressed elegantly.", "She holds an umbrella.",
    "She drops her phone near Kasun's three-wheeler.", "Kasun picks up the phone.", "He runs after her.",
    None, "Anudi turns around.", None, "She looks at his little business.", None, "Kasun smiles.", None,
    "Anudi smiles back.", "Her phone rings.", None, "Her smile disappears.", "She looks at Kasun one more time.", None,
    "She walks away.", "Kasun watches her leave.", "Rain continues to pour on the road.",
]
STALL = "Stall (Kasun’s three-wheeler, frame left)"
MID = "Mid-pavement (under umbrella between stall and car)"


def mark(block: int, who: str, zone: str, holding_: str) -> dict[str, Any]:
    return {"block": block, "who": who, "zone": zone, "facing": "", "frame_side": "", "holding": holding_}


# What Jonathan wrote: nobody holds anything until Kasun has the phone at b5; Anudi gets "umbrella, phone" at b7 and
# Kasun is never marked giving the phone up.
AS_PLANNED = [mark(0, "Anudi", "Car curb (frame right)", "—"), mark(0, "Kasun", STALL, "—"),
              mark(5, "Kasun", MID, "phone"), mark(7, "Anudi", MID, "umbrella, phone"),
              mark(19, "Anudi", "Down the footpath (frame right, away)", "umbrella, phone"),
              mark(20, "Kasun", STALL, "—")]
# What the new check asks for: her phone from the start, the umbrella at b2, the drop at b3, the pick-up at b4
FIXED = [mark(0, "Anudi", "Car curb (frame right)", "her phone"), mark(0, "Kasun", STALL, "—"),
         mark(2, "Anudi", "Car curb (frame right)", "phone, umbrella"), mark(3, "Anudi", "Car curb (frame right)",
                                                                             "umbrella"),
         mark(4, "Kasun", STALL, "phone"), mark(5, "Kasun", MID, "phone"), mark(7, "Anudi", MID, "umbrella, phone"),
         mark(20, "Kasun", STALL, "—")]
OPENS = ["The sedan stops; Anudi steps out.", "The umbrella snaps open.", "The phone slips and slaps the water."]


def scene_s() -> SceneS:
    blocks = [BlockS(index=i, kind="action" if t else "dialogue", text=t or "", line_id=None if t else f"L{i}",
                     speaker="" if t else "Kasun") for i, t in enumerate(SCRIPT)]
    return SceneS(blocks=blocks, cast=["Kasun", "Anudi"])


def plan_with(marks: list[dict[str, Any]]) -> JonathanWire:
    plan = JonathanWire.model_construct()
    object.__setattr__(plan, "staging", StagingW.model_validate({"zones": [STALL, MID], "marks": marks}))
    return plan


# ── reading a holding ──────────────────────────────────────────────────────────────────────────────


def test_a_holding_is_read_as_things_with_their_state_and_an_empty_hand_is_nothing():
    assert [t.key for t in things_of("umbrella, phone")] == ["umbrella", "phone"]
    assert [t.key for t in things_of("the phone and a bag")] == ["phone", "bag"]
    assert things_of("—") == [] and things_of("nothing") == [] and things_of("") == []
    assert thing_of("the open black umbrella") == holding.Thing("umbrella", "open black umbrella", "open")
    assert thing_of("handbag on her shoulder").worn  # carried, but not in a hand
    assert thing_of("cup of tea").key == "cup"


def test_a_props_state_comes_from_the_last_sentence_that_sets_it():
    assert state_in("umbrella", OPENS) == "open"
    assert state_in("umbrella", ["She opens the umbrella.", "She folds the umbrella away."]) == "folded"
    assert state_in("umbrella", ["She holds an umbrella."]) == ""


# ── one holder per thing ──────────────────────────────────────────────────────────────────────────


def test_a_thing_given_to_someone_leaves_the_givers_hand_even_when_the_planner_forgets_to_mark_it():
    ledger = Ledger.of(AS_PLANNED)
    assert ledger.at(6)["phone"][0] == "Kasun"
    assert ledger.at(8)["phone"][0] == "Anudi"  # Kasun's b5 mark still says "phone": one holder wins
    assert ledger.at(20)["phone"][0] == "Anudi" and "Kasun" not in {w for w, _ in ledger.at(21).values()}


def test_a_drop_lets_go_and_a_pick_up_takes():
    ledger = Ledger.of(FIXED)
    assert ledger.at(3)["phone"][0] == "Anudi"
    assert "phone" not in ledger.at(4)  # on the ground
    assert ledger.at(5)["phone"][0] == "Kasun"


# ── the hands of each shot (blocks as stored on the shot rows) ──────────────────────────────────────


def hands(marks: list[dict[str, Any]], start: int, end: int, seen: list[str], framing: str = "MS",
          video: bool = False) -> str:
    return shot_hands(Ledger.of(marks), block_start=start, block_end=end, seen=seen, framing=framing,
                      earlier=OPENS, video=video).sentence


def test_s07_she_turns_to_his_voice_without_her_phone_which_is_still_his():
    said = hands(FIXED, 6, 8, ["Anudi"], "MCU")
    assert "The phone is not in this frame." in said
    assert "Anudi holds the open umbrella in one hand." in said
    assert "Anudi holds the phone" not in said and "holds the open umbrella in one hand and the phone" not in said


def test_s08_the_handover_insert_opens_with_the_phone_in_his_hand_and_her_umbrella_in_hers():
    said = hands(FIXED, 8, 8, ["Kasun", "Anudi"], "INSERT")  # an added shot: no block of its own
    assert "Kasun holds the phone in one hand." in said
    assert "Anudi holds the open umbrella in one hand." in said
    assert "Even this close" in said


def test_s11_kasun_listens_with_no_phone():
    said = hands(FIXED, 10, 11, ["Kasun"], "MCU")
    assert "Kasun is not holding the phone or the umbrella." in said
    assert "The phone is not in this frame." in said


def test_s14_both_things_one_in_each_hand():
    said = hands(FIXED, 14, 15, ["Anudi"], "INSERT")
    assert ("Anudi holds the open umbrella in one hand and the phone in the other hand" in said
            or "Anudi holds the phone in one hand and the open umbrella in the other hand" in said)
    assert "neither is put down" in said


def test_the_video_prompt_says_what_passes_between_hands_during_the_shot():
    said = hands(FIXED, 4, 6, ["Kasun"], "MWS", video=True)
    assert "During the shot Kasun takes the phone." in said
    assert "passes from Kasun's hand to Anudi's" in hands(FIXED, 7, 8, ["Kasun", "Anudi"], "TWO", video=True)


def test_an_empty_hand_is_not_news_unless_someone_else_has_the_thing():
    assert "not holding" not in hands(FIXED, 0, 1, ["Anudi"], "MCU")  # she has it: no negative about her
    assert "Kasun is not holding the phone" in hands(FIXED, 0, 1, ["Kasun"], "MCU")  # she arrives with it: say so
    assert hands(AS_PLANNED, 0, 1, ["Kasun", "Anudi"], "WIDE") == ""  # the planner gave nobody anything: say nothing


def test_no_ledger_no_sentence():
    assert shot_hands(None, block_start=0, block_end=1, seen=["Anudi"]) == holding.Hands()
    assert shot_hands(Ledger.of([mark(0, "Anudi", "x", "")]), block_start=0, block_end=1, seen=["Anudi"]).sentence == ""


# ── the check that makes Jonathan mark every change of hands ─────────────────────────────────────────


def test_the_check_finds_the_three_gaps_in_what_jonathan_wrote():
    found = _holding(scene_s(), plan_with(AS_PLANNED))
    keys = sorted(p.key for p in found)
    assert keys == ["holding:before:3:phone", "holding:take:2:umbrella", "holding:take:4:phone"]
    assert all(p.fix == "repair" and p.code == "holding" for p in found)


def test_the_check_passes_marks_that_follow_the_script():
    assert _holding(scene_s(), plan_with(FIXED)) == []


def test_the_check_reads_no_breath_or_look_as_a_thing():
    blocks = [BlockS(index=0, text="She takes a deep breath and holds his gaze."),
              BlockS(index=1, text="He takes a step back.")]
    assert _holding(SceneS(blocks=blocks, cast=["Anudi"]), plan_with([])) == []


# ── who is on screen, and where a voice comes from (Jonathan's write step) ──────────────────────────


PEOPLE = {"kasun": "K", "anudi": "A"}


class _Shot:  # only what on_screen_of and intent_of read
    def __init__(self, subjects: list[Any], frame_subjects: list[str], over: str = "", lines: list[str] | None = None,
                 beats: list[dict[str, str]] | None = None) -> None:
        self.ir = {"subjects": subjects, "first_frame": {"subjects": frame_subjects}, "beats": beats or []}
        self.over, self.lines, self.why = over, lines or [], "why"


def test_s05_a_name_in_passing_does_not_put_kasun_in_the_frame():
    shot = _Shot([{"id": "C02", "description": "Anudi’s hand", "action": "fumbles the phone"},
                  {"id": "C01", "description": "Kasun’s canopy color", "action": "static background cue"}],
                 ["phone", "Anudi’s fingertips"])
    assert write.on_screen_of(shot, PEOPLE, {"C01": "K", "C02": "A"}) == ["A"]


def test_an_action_naming_someone_does_not_put_them_in_the_frame():
    shot = _Shot([{"id": "C02", "description": "Anudi", "action": "looks at Kasun one last time"}], ["Anudi"])
    assert write.on_screen_of(shot, PEOPLE) == ["A"]


def test_a_subject_with_only_a_code_is_that_person():
    shot = _Shot([{"id": "C01", "description": "a slim man at the stall", "action": "waits"}], [])
    assert write.on_screen_of(shot, PEOPLE, {"C01": "K"}) == ["K"]


def item(index: int, text: str, line: str | None = None, delivery: str = "") -> Item:
    return Item(index, "dialogue" if line else "action", text, "", None, delivery, line)


def test_s07_kasun_calling_out_is_a_voice_off_screen_not_a_phone_call():
    shot = _Shot([{"id": "C02", "description": "Anudi under the umbrella", "action": "turns toward the voice"}],
                 ["Anudi"], over="Anudi", lines=["L6"],
                 beats=[{"action": "She starts to turn, registering the call.",
                         "performance": "Her eyes soften as she sees the phone in his hand."}])
    rows = {"L6": {"id": "line-6", "character_id": "K"}}
    got = write.intent_of(shot, [item(6, "Miss! Your phone!", "line-6"), item(7, "Anudi turns around.")], PEOPLE,
                          rows)
    assert got["heard_only"] == ["K"] and got["voice_source"] == "off_screen"


def test_s15_the_fathers_line_marked_on_the_phone_is_a_phone_call():
    shot = _Shot([{"id": "C02", "description": "Anudi", "action": "listens"}], ["Anudi"], over="Anudi", lines=["L15"])
    rows = {"L15": {"id": "line-15", "character_id": "F"}}
    got = write.intent_of(shot, [item(15, "Anudi, where are you?", "line-15", "on the phone")], PEOPLE, rows)
    assert got["heard_only"] == ["F"] and got["voice_source"] == "phone"


def test_jonathans_list_of_who_is_seen_is_final_like_a_persons():
    characters = [{"id": "K", "name": "Kasun", "aliases": []}, {"id": "A", "name": "Anudi", "aliases": []}]
    own = [item(3, "She drops her phone near Kasun's three-wheeler.")]
    intent = {"on_screen": ["A"], "heard_only": [], "by": "jonathan", "purpose": "", "what_we_see": ""}
    assert staging(own, characters, {"intent": intent}).on_screen == ["A"]
    assert ShotIntent.of({"intent": {**intent, "by": "model"}}) is not None
    assert staging(own, characters, {"intent": {**intent, "by": "model"}}).on_screen == ["K", "A"]  # unchanged


# ── the frame: its prompt and its reference pictures ──────────────────────────────────────────────


def scene_row(marks: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": "s", "location_id": "road", "script": [{"kind": "action" if t else "dialogue", "text": t or ""}
                                                         for t in SCRIPT],
            "jonathan": {"plan": {"staging": {"marks": marks}, "shots": [
                {"n": 4, "ir": {"beats": [{"action": "The umbrella snaps open."}]}}]}}}


def shot_row(number: int, start: int, end: int, framing: str = "MCU", setting: str = "") -> dict[str, Any]:
    return {"number": number, "block_start": start, "block_end": end, "framing": framing, "planner": "jonathan",
            "ir": {"setting": setting, "first_frame": {"setting": setting}}}


CANON = [{"id": "K", "kind": "character", "name": "Kasun"}, {"id": "A", "kind": "character", "name": "Anudi"},
         {"id": "road", "kind": "location", "name": "Colombo Road"},
         {"id": "stall", "kind": "location", "name": "Kasun's Food Three-Wheeler"},
         {"id": "home", "kind": "location", "name": "Anudi's Family Home"},
         {"id": "phone", "kind": "prop", "name": "Smartphone"}, {"id": "umb", "kind": "prop", "name": "Umbrella"},
         {"id": "pen", "kind": "prop", "name": "Pen"}]


def sheet(row: dict[str, Any]) -> bool:
    return row["id"] not in ("umb", "home")  # the umbrella has no sheet yet


def test_s11_the_phone_a_person_added_to_every_shot_is_left_out_while_anudi_holds_it_off_screen():
    refs = holding.references_for(scene_row(FIXED), shot_row(11, 10, 11), CANON, ["K", "road", "phone"],
                                  {"K": "Kasun"}, has_sheet=sheet)
    assert [c for c, _ in refs] == ["K", "road"]


def test_s09_the_phone_she_holds_is_attached_and_labelled_with_its_holder():
    refs = holding.references_for(scene_row(FIXED), shot_row(9, 8, 9), CANON, ["A", "road", "phone"],
                                  {"A": "Anudi"}, has_sheet=sheet)
    assert refs == [("A", ""), ("road", ""), ("phone", "held by Anudi")]


def test_a_held_prop_with_a_sheet_is_attached_even_when_nobody_added_it():
    refs = holding.references_for(scene_row(FIXED), shot_row(9, 8, 9), CANON, ["A", "road"], {"A": "Anudi"},
                                  has_sheet=sheet)
    assert ("phone", "held by Anudi") in refs and "umb" not in [c for c, _ in refs]  # no sheet, not added


def test_the_stall_is_attached_when_the_shot_is_at_it():
    at_stall = holding.references_for(scene_row(FIXED), shot_row(2, 2, 2, setting="Under the canopy of the stall"),
                                      CANON, ["K", "road"], {"K": "Kasun"}, has_sheet=sheet)
    assert [c for c, _ in at_stall] == ["K", "road", "stall"]  # Kasun stands in the stall's zone
    away = holding.references_for(scene_row(FIXED), shot_row(13, 13, 14, setting="Curb under umbrella"), CANON,
                                  ["A", "road"], {"A": "Anudi"}, has_sheet=sheet)
    assert "stall" not in [c for c, _ in away]


def test_a_prop_on_the_ground_stays_when_the_shot_shows_it():
    s6 = shot_row(6, 4, 5, "MWS")
    s6["ir"]["first_frame"]["subjects"] = ["Kasun", "the phone in the puddle"]
    refs = holding.references_for(scene_row(FIXED), s6, CANON, ["K", "road", "phone"], {"K": "Kasun"},
                                  has_sheet=sheet)
    assert "phone" in [c for c, _ in refs]


def test_the_frame_prompt_says_who_holds_what_after_the_people():
    said = holding.hands_for(scene_row(FIXED), shot_row(14, 14, 15, "INSERT"), ["Anudi"]).sentence
    prompt = frame_prompt(ir={"first_frame": {"composition": "Phone in hand"}}, camera=default_camera("INSERT"),
                          aspect_ratio="16:9", cast=[], hands=said)
    assert said.startswith("Hands: ") and said in prompt
    assert "open umbrella" in said  # opened in shot 4


def test_names_and_matches():
    assert canon_match("phone", CANON)["id"] == "phone"
    assert canon_match("umbrella", [{"kind": "prop", "name": "Foldable umbrella", "id": 1},
                                    {"kind": "prop", "name": "Umbrella", "id": 2}])["id"] == 2
    assert canon_match("cheque", CANON) is None
    assert names_place("Kasun's Food Three-Wheeler", STALL)
    assert not names_place("Kasun's Food Three-Wheeler", "Kasun at the curb")
    assert not names_place("Anudi's Family Home", "Anudi under the umbrella")


@pytest.mark.parametrize("framing", ["CU", "MCU", "INSERT"])
def test_a_close_shot_keeps_what_is_held_in_the_picture(framing: str):
    assert "Even this close" in hands(FIXED, 14, 15, ["Anudi"], framing)
    assert "Even this close" not in hands(FIXED, 14, 15, ["Anudi"], "WIDE")


def test_it_is_the_thing_an_earlier_action_named():
    blocks = [BlockS(index=0, text="She accidentally drops her phone near Kasun's three-wheeler."),
              BlockS(index=1, text="Kasun picks it up and runs after her.")]
    found = _holding(SceneS(blocks=blocks, cast=["Kasun", "Anudi"]), plan_with([]))
    assert sorted(p.key for p in found) == ["holding:before:0:phone", "holding:take:1:phone"]


@pytest.mark.parametrize(("written", "keys"), [
    ("umbrella, phone at ear", ["umbrella", "phone"]),
    ("Anudi’s phone", ["phone"]),
    ("tea glass, then phone briefly at b6", ["glass", "phone"]),
    ("the open umbrella over her head", ["umbrella"]),
])
def test_a_holding_written_loosely_still_names_its_things(written: str, keys: list[str]):
    assert [t.key for t in things_of(written)] == keys


# ── what the live Episode 1 plan (2026-11-06, tests/eval/jonathan/spike/episode1/1.json) taught ─────────────────────

EP1 = [mark(1, "Kasun", STALL, ""), mark(4, "Anudi", "curb", "umbrella, handbag, phone"),
       mark(5, "Anudi", "curb", "umbrella, handbag"), mark(6, "Kasun", MID, "phone"),
       mark(8, "Anudi", MID, "umbrella, handbag, phone")]


def test_what_a_person_arrives_with_is_theirs_from_the_start_of_that_block():
    said = shot_hands(Ledger.of(EP1), block_start=4, block_end=5, seen=["Anudi"]).sentence
    assert "Anudi holds the umbrella in one hand and the phone in the other hand" in said or \
        "Anudi holds the phone in one hand and the umbrella in the other hand" in said


def test_a_later_change_still_happens_during_its_block():
    assert "phone" in Ledger.of(EP1).at(5)  # the drop at b5: as the drop shot opens, she still has it
    assert Ledger.of(EP1).at(6).get("phone") is None  # the pick-up at b6: it is on the ground as that shot opens


def test_a_bag_is_on_the_shoulder_and_never_takes_a_hand_or_crowds_the_negatives():
    said = shot_hands(Ledger.of(EP1), block_start=9, block_end=10, seen=["Anudi"]).sentence
    assert "Anudi has the handbag." in said and "and also carries" not in said
    kasun = shot_hands(Ledger.of(EP1), block_start=9, block_end=10, seen=["Kasun"]).sentence
    assert "handbag" not in kasun and "Kasun is not holding the phone or the umbrella." in kasun
    assert thing_of("handbag in her hand").worn is False


def test_an_insert_of_the_phone_is_never_told_the_phone_is_not_in_frame():
    said = shot_hands(Ledger.of(EP1), block_start=5, block_end=6, seen=[],
                      shown="The phone slips from a gloved hand into a puddle").sentence
    assert "phone is not in this frame" not in said and "umbrella is not in this frame" in said
