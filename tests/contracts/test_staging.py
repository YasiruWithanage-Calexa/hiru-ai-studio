"""contracts.staging: who the camera sees, who is only heard (plan/2026-11-01)."""
from __future__ import annotations

from contracts import sceneplan
from contracts.producer import CameraSettings, default_camera, frame_prompt, shot_items
from contracts.shotplan import Item
from contracts.staging import (
    ScenePlan,
    ShotIntent,
    coverage_checks,
    heard_marked,
    shot_cast,
    staging,
    staging_checks,
    unseen_sentence,
    voice_source,
)
from tests.services.production_fixture import ANUDI, FATHER, KASUN, PHONE_CANON, phone_scene

CHARACTERS = [c for c in PHONE_CANON if c["kind"] == "character"]
NAMES = {str(c["id"]): str(c["name"]) for c in CHARACTERS}


def call_shot(delivery: str = "on the phone", **row) -> tuple[list[Item], dict]:
    scene, lines, shots = phone_scene(delivery=delivery)
    shot = {**shots[1], **row}
    items = shot_items(sceneplan.items_for(scene["script"], lines), shot["block_start"], shot["block_end"])
    return items, shot


def test_a_phone_voice_is_heard_not_seen_by_rule():
    items, shot = call_shot()
    line = next(i for i in items if i.is_line)
    assert heard_marked(line) and voice_source(items) == "phone"
    staged = staging(items, CHARACTERS, shot)
    assert staged.on_screen == [ANUDI] and staged.heard_only == [FATHER]
    assert staged.voice_source == "phone" and staged.source == "rules"
    assert FATHER in shot_cast(items, CHARACTERS, shot), "still in the shot: his voice pin and card count"


def test_a_marked_call_stays_off_screen_whatever_a_model_says_unless_a_person_adds_him():
    items, shot = call_shot(design={"on_screen": [ANUDI, FATHER]})
    assert staging(items, CHARACTERS, shot).on_screen == [ANUDI]
    intent = ShotIntent(on_screen=[ANUDI, FATHER], by="model").model_dump()
    assert staging(items, CHARACTERS, {**shot, "intent": intent}).on_screen == [ANUDI]
    edits = {"cast": {"add": [FATHER], "remove": []}}
    assert staging(items, CHARACTERS, {**shot, "person_edits": edits}).on_screen == [ANUDI, FATHER]


def test_an_unmarked_call_is_fixed_by_the_intent_and_the_dop():
    """The old build left the father's delivery empty, so the shot reads as dialogue."""
    items, shot = call_shot(delivery="", sound_mode="dialogue")
    assert staging(items, CHARACTERS, shot).on_screen == [ANUDI, FATHER], "rules alone cannot tell"
    by_dop = staging(items, CHARACTERS, {**shot, "design": {"on_screen": [ANUDI]}})
    assert (by_dop.on_screen, by_dop.heard_only, by_dop.source) == ([ANUDI], [FATHER], "design")
    intent = ShotIntent(on_screen=[ANUDI], heard_only=[FATHER], voice_source="phone", by="model")
    by_intent = staging(items, CHARACTERS, {**shot, "intent": intent.model_dump(),
                                            "design": {"on_screen": [ANUDI, FATHER]}})
    assert (by_intent.on_screen, by_intent.source, by_intent.voice_source) == ([ANUDI], "intent", "phone")


def test_a_persons_intent_is_exact_and_a_models_leaves_gaps_to_the_rules():
    items, shot = call_shot()
    model = ShotIntent(on_screen=[], heard_only=[FATHER], by="model")
    assert staging(items, CHARACTERS, {**shot, "intent": model.model_dump()}).on_screen == [ANUDI]
    person = ShotIntent(on_screen=[], heard_only=[FATHER], by="person")
    assert staging(items, CHARACTERS, {**shot, "intent": person.model_dump()}).on_screen == []
    # an intent can bring someone the script only implies into the shot
    kasun = ShotIntent(on_screen=[ANUDI, KASUN], by="model")
    assert KASUN in shot_cast(items, CHARACTERS, {**shot, "intent": kasun.model_dump()})


def test_checks_name_what_is_wrong():
    items, shot = call_shot()
    staged = staging(items, CHARACTERS, shot)
    ir = {"first_frame": {"composition": "Anudi beside Anudi's Father at the stall", "subjects": []}}
    checks = staging_checks(staged=staged, names=NAMES, sound_mode="dialogue", speaker_ids=[FATHER], ir=ir,
                            design_on_screen=[ANUDI], intent=ShotIntent(on_screen=[ANUDI, KASUN], by="model"))
    labels = {c.label: c.tone for c in checks}
    assert labels["Heard only · Anudi's Father (phone)"] == "pass"
    assert labels["Speaker not on screen · Anudi's Father"] == "advisory"
    assert labels["First frame shows Anudi's Father, who is only heard"] == "advisory"
    assert labels["The DoP and the intent differ on who is seen · Kasun"] == "advisory"
    assert all(c.code == "staging" for c in checks)


def test_the_frame_prompt_says_who_is_not_there():
    items, shot = call_shot()
    staged = staging(items, CHARACTERS, shot)
    sentence = unseen_sentence(staged, NAMES)
    assert sentence == ("Anudi's Father is not in this place and not in the frame (heard through the phone "
                        "held by Anudi, thin and compressed like a real call).")
    prompt = frame_prompt(ir={}, camera=default_camera("MCU"), aspect_ratio="16:9", cast=[], unseen=sentence)
    assert sentence in prompt


def test_coverage_checks_flag_one_size_and_repeated_setups():
    cams = [CameraSettings.model_validate(default_camera("MCU").model_dump()) for _ in range(4)]
    per_shot = coverage_checks(["MCU"] * 4, cams, ["S01", "S02", "S03", "S04"])
    assert [c.label for c in per_shot[0]] == ["Every shot in the scene is a medium close-up"]
    assert [c.label for c in per_shot[2]] == ["Same setup as S02"]
    varied = coverage_checks(["WIDE", "MCU", "CU"], [default_camera(f) for f in ("WIDE", "MCU", "CU")],
                             ["S01", "S02", "S03"])
    assert varied == [[], [], []]


def test_stored_json_reads_safely():
    assert ShotIntent.of({"intent": {}}) is None and ShotIntent.of({"intent": {"by": "nobody"}}) is None
    assert ScenePlan.of({"coverage": {"axis": "street side", "by": "model"}}).text() == "Axis: street side"
    it = ShotIntent(purpose="the call lands", by="model", made_for="v1:abc")
    assert it.stale("v2:abc") and not it.stale("v1:abc")
    assert it.stamp() != ShotIntent(purpose="the call", by="model").stamp()
