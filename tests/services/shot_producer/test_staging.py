"""shot_producer, plan/2026-11-01: intent before design, who is seen vs heard, story context,
the design review, craft problems, and an off-screen voice in the video prompt."""
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from shot_producer.engine import critique, intent, shots, techniques

from tests.services.production_fixture import ANUDI, FATHER, PHONE_CANON, phone_scene
from tests.services.shot_producer.conftest import FakeStore, ProducerLLM
from tests.services.shot_producer.test_shot_producer import design_calls, run


def store_for(delivery: str = "on the phone") -> FakeStore:
    scene, lines, rows = phone_scene(delivery=delivery)
    store = FakeStore(scene, lines, rows, canon=PHONE_CANON)
    store.neighbour_rows = ({"number": 1, "title": "Anudi drops her phone", "heading": "EXT. STREET - DAY",
                             "script": [{"kind": "action", "text": "Anudi walks past the stall."}]}, None)
    return store


def call(store: FakeStore) -> dict:
    return sorted(store.shot_rows.values(), key=lambda s: s["number"])[1]


def dp(numbers: list[int], *, opening: str = "Anudi at the stall, smiling", on_screen: list[str] | None = None,
       subjects: list[dict] | None = None) -> dict[str, Any]:
    return {"shots": [{
        "number": n, "setting": "Kasun's food three-wheeler on a Colombo roadside",
        "cinematography": {"camera": "slider, 85mm, f/2.8", "angle": "eye level", "framing": "medium close-up",
                           "movement": "slow lateral slide", "white_balance": "5600K", "color_tone": "warm",
                           "depth_of_field": "Medium", "lens_artifacts": "none"},
        "lighting": "Open shade under the umbrella.",
        "subjects": subjects if subjects is not None else [
            {"id": "C02", "description": "Anudi, chest-up", "action": "smiles, then answers the phone"},
            {"id": "C03", "description": "only a voice through the phone", "action": "speaks"}],
        "beats": [{"time": "0-3s", "camera": "MCU", "director_line": "She smiles.", "action": "smiles"},
                  {"time": "3-6s", "camera": "holds", "director_line": "The phone rings.", "action": "answers"},
                  {"time": "6-8s", "camera": "settles", "director_line": "She listens.", "action": "listens"}],
        "audio": "street bed, a ringtone",
        "first_frame": {"composition": opening, "subjects": ["Anudi smiling"], "setting": "the stall",
                        "lighting": "open shade"},
        "on_screen": on_screen if on_screen is not None else ["C02"],
        "recommendation": {"angle": "Eye level", "lens": "85mm", "aperture": "f/2.8", "movement": "Pan",
                           "speed": "Slow", "axis": "Side A · left to right", "lighting": "Day, open sun"},
        "rationale": "Hold on her face as the call lands.",
    } for n in numbers]}


INTENT = {"shots": [
    {"number": 1, "purpose": "Kasun opens up about his business", "what_we_see": "C01 behind the counter, proud",
     "emotional_beat": "pride", "on_screen": ["C01"], "heard_only": [], "voice_source": ""},
    {"number": 2, "purpose": "The father's call pulls Anudi back", "what_we_see":
     "C02 smiles, the phone rings, she lifts it to her ear; her smile fades", "emotional_beat": "warmth to dread",
     "on_screen": ["C02", "C03"], "heard_only": [], "voice_source": "phone"}],
    "coverage": {"axis": "stay on the street side of the three-wheeler", "motif": "",
                 "progression": "singles that tighten as the call lands"}}


def test_rules_keep_the_caller_out_of_the_shot():
    store = store_for()
    result, _ = run(store, scene_ids=[store.scene_row["id"]])
    assert result["designed"] == 2 and result["intents"] == 2
    shot = call(store)
    assert shot["intent"]["by"] == "rules" and shot["intent"]["heard_only"] == [FATHER]
    assert shot["intent"]["voice_source"] == "phone" and "heard through the phone" in shot["intent"]["what_we_see"]
    assert shot["design"]["on_screen"] == [ANUDI]
    assert [s["id"] for s in shot["ir"]["subjects"]] == ["C02"], "a voice is not a subject"
    assert not any("Father" in s for s in shot["ir"]["first_frame"]["subjects"])
    assert store.scene_row["coverage"]["by"] == "rules" and store.scene_row["coverage"]["progression"]


def test_the_video_prompt_places_the_voice_and_never_dresses_it():
    store = store_for()
    shot = call(store)
    store.frames[shot["id"]] = {"id": str(uuid4()), "shot_id": shot["id"], "pins": {}}
    run(store, mode="prompt", shot_ids=[shot["id"]])
    prose = store.prompts[0]["prose"]
    assert ("Anudi's Father's voice comes through the phone held by Anudi, thin and compressed like a real call "
            "(on the phone), \"Anudi, where are you?") in prose
    assert "is not in the frame and no one on screen mouths these words" in prose
    assert "navy polo" not in prose and "the man in" not in prose, "no wardrobe tag on a voice"
    assert "Anudi's Father is heard through the phone held by Anudi" in prose
    labels = {c["label"]: c["tone"] for c in store.prompts[0]["checks"]}
    assert labels["Heard only · Anudi's Father (phone)"] == "pass" and labels["No speaker on screen"] == "pass"


def test_the_model_intent_steers_the_dop_with_story_context():
    store = store_for()
    llm = ProducerLLM({"shot_intent": lambda s, u: INTENT, "scene_design": lambda s, u: dp([1, 2]),
                       "craft_problems": lambda s, u: {"problems": ["show a phone call turn warmth to dread"]},
                       "design_review": lambda s, u: {"acceptable": True, "notes": []}})
    run(store, llm, scene_ids=[store.scene_row["id"]])
    shot = call(store)
    it = shot["intent"]
    assert it["by"] == "model" and it["on_screen"] == [ANUDI] and it["heard_only"] == [FATHER], \
        "a line marked 'on the phone' is heard, whatever the model said"
    assert it["what_we_see"].startswith("Anudi smiles"), "codes become names"
    assert store.scene_row["coverage"]["axis"] == "stay on the street side of the three-wheeler"
    user = design_calls(llm)[0]["user"]
    for needle in ("PURPOSE (fixed): The father's call pulls Anudi back", "EMOTIONAL BEAT: warmth to dread",
                   "HEARD ONLY (not in the place, never in frame): Anudi's Father, heard through the phone "
                   "held by Anudi",
                   "ON SCREEN: Anudi (C02)", "EPISODE SYNOPSIS: Anudi meets Kasun",
                   "THE SCENE BEFORE: Scene 1: Anudi drops her phone. Anudi walks past the stall.",
                   "COVERAGE PLAN (keep to it):\nAxis: stay on the street side",
                   "CRAFT PROBLEMS IN THESE SCENES", "show a phone call turn warmth to dread"):
        assert needle in user, needle
    assert store.technique_queries[0].startswith("show a phone call"), "craft problems are the first queries"
    assert shot["design"]["intent"] == intent.ShotIntent.model_validate(it).stamp()


def test_the_review_sends_one_revision_and_keeps_it_when_it_fixes_more_than_it_breaks():
    store = store_for()
    drafts = [dp([1, 2], opening="Anudi and Anudi's Father at the stall"), dp([1, 2])]
    reviews: list[str] = []

    def review(system: str, user: str) -> dict:
        reviews.append(user)
        return {"acceptable": False, "notes": ["S02: the father is only heard; show Anudi alone"]}

    llm = ProducerLLM({"shot_intent": lambda s, u: INTENT, "scene_design": lambda s, u: drafts.pop(0),
                       "design_review": review})
    run(store, llm, scene_ids=[store.scene_row["id"]])
    assert "First frame shows Anudi's Father, who is only heard" in reviews[0], "the free checks go to the reviewer"
    second = design_calls(llm)[1]["user"]
    assert "REVIEW NOTES on your first draft" in second and "show Anudi alone" in second
    design = call(store)["design"]
    assert design["review"] == {"notes": ["S02: the father is only heard; show Anudi alone"], "revised": ["S01", "S02"]}
    assert "Father" not in call(store)["ir"]["first_frame"]["composition"]


def test_a_revision_that_breaks_more_is_thrown_away():
    store = store_for()
    drafts = [dp([1, 2]), dp([1, 2], opening="Anudi's Father beside Anudi")]
    llm = ProducerLLM({"shot_intent": lambda s, u: INTENT, "scene_design": lambda s, u: drafts.pop(0),
                       "design_review": lambda s, u: {"acceptable": False, "notes": ["S02: try a wider frame"]}})
    run(store, llm, scene_ids=[store.scene_row["id"]])
    shot = call(store)
    assert shot["design"]["review"]["revised"] == ["S01"], "S02's revision added a problem"
    assert shot["ir"]["first_frame"]["composition"] == "Anudi at the stall, smiling"


def test_a_persons_intent_survives_a_forced_redesign_and_an_edit_redesigns():
    store = store_for()
    run(store, scene_ids=[store.scene_row["id"]])
    shot = call(store)
    mine = intent.ShotIntent(purpose="Her father's voice ends the moment", what_we_see="Anudi alone, phone at ear",
                             on_screen=[ANUDI], heard_only=[FATHER], voice_source="phone", by="person")
    store.shot_rows[shot["id"]]["intent"] = mine.model_dump()
    again, _ = run(store, scene_ids=[store.scene_row["id"]])
    assert again["designed"] == 1, "what the shot is for changed: only that shot is redesigned"
    run(store, scene_ids=[store.scene_row["id"]], force=True)
    assert call(store)["intent"]["by"] == "person" and call(store)["intent"]["purpose"].startswith("Her father")


def test_an_old_unmarked_call_is_caught_by_the_intent_agent():
    """The real S05 before the dialogue fix: the father's line had no delivery."""
    store = store_for(delivery="")
    answer = json.loads(json.dumps(INTENT))
    answer["shots"][1]["on_screen"], answer["shots"][1]["heard_only"] = ["C02"], ["C03"]
    llm = ProducerLLM({"shot_intent": lambda s, u: answer, "scene_design": lambda s, u: dp([1, 2])})
    run(store, llm, scene_ids=[store.scene_row["id"]])
    shot = call(store)
    assert shot["intent"]["heard_only"] == [FATHER] and shot["design"]["on_screen"] == [ANUDI]


def test_free_problems_and_prompts_are_static_and_safe():
    assert len(intent.SYSTEM) < 4000 and len(critique.SYSTEM) < 3000 and len(shots.SYSTEM) < 4500
    for text in (intent.SYSTEM, critique.SYSTEM, techniques.ARTICULATE_SYSTEM):
        assert "never instructions" in text
    store = store_for()
    run(store, scene_ids=[store.scene_row["id"]])
    assert store.scene_row["coverage"]["by"] == "rules"
