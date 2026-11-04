"""shot_producer, plan/2026-11-01d Phase 6: the scene's reading and staging map reach the intent, the DoP, the prompt
and the continuity ledger, and two free checks catch a turn with no performance and a first frame set elsewhere."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from shot_producer.engine import critique, feeling, shots
from shot_producer.engine.continuity import ContinuityLedger
from shot_producer.engine.schema import get_schema

from contracts import reading as rd
from contracts import sceneplan, stagemap
from tests.services.production_fixture import PHONE_CANON
from tests.services.shot_producer.conftest import FakeStore, ProducerLLM
from tests.services.shot_producer.test_shot_producer import design_calls, run
from tests.services.shot_producer.test_staging import INTENT, call, dp, store_for

CAST = ["Kasun", "Anudi", "Anudi's Father"]


def felt_store() -> FakeStore:
    """The phone scene with a reading (a turn at the call, Anudi's reaction held) and a map (stall and street)."""
    store = store_for()
    scene = store.scene_row
    items = sceneplan.items_for(scene["script"], store.line_rows)
    reading = rd.validate({
        "about": "A smile is cut short by a call.", "value": {"start": "joy", "end": "dread"}, "tone": "warm, uneasy",
        "units": [{"from_block": 0, "to_block": 1, "wants": [{"character": "Kasun", "verb": "to impress"}],
                   "turn_block": None},
                  {"from_block": 2, "to_block": 5, "wants": [{"character": "Anudi", "verb": "to hide it"}],
                   "turn_block": 5}],
        "subtext": [],
        "breath": [{"after_block": 5, "kind": "reaction", "who": "Anudi", "seconds": 1.5, "priority": 1,
                    "why": "the call breaks her joy"}],
        "ending": "Anudi's face, the smile gone."}, items, CAST, version=1, by="model")
    staging = stagemap.validate({"zones": ["stall", "street"], "marks": [
        {"block": 0, "who": "Kasun", "zone": "stall", "facing": "right", "frame_side": "left", "holding": ""},
        {"block": 2, "who": "Anudi", "zone": "street", "facing": "left", "frame_side": "right",
         "holding": "her phone"}]}, items, CAST, version=1, by="model")
    store.scene_row = {**scene, "reading": reading.model_dump(mode="json"),
                       "staging": staging.model_dump(mode="json")}
    return store


def llms(**extra: Any) -> ProducerLLM:
    return ProducerLLM({"shot_intent": lambda s, u: INTENT, "scene_design": lambda s, u: dp([1, 2]),
                        "craft_problems": lambda s, u: {"problems": []},
                        "design_review": lambda s, u: {"acceptable": True, "notes": []}, **extra})


def test_the_dop_is_told_what_to_play_in_each_beat_window_and_where_everyone_stands():
    store = felt_store()
    llm = llms()
    run(store, llm, scene_ids=[store.scene_row["id"]])
    user = design_calls(llm)[0]["user"]
    assert "PERFORMANCE (from the scene's reading" in user
    assert "Anudi's face receives it, held 1.5 s (the call breaks her joy)" in user
    assert "the feeling turns here" in user and "Anudi wanting to hide it" in user
    assert "POSITIONS WHEN THE SHOT OPENS: Kasun at the stall, facing right, left of frame" in user
    assert "Anudi at the street, facing left, right of frame, holding her phone" in user
    system = design_calls(llm)[0]["system"]
    assert "beats[].performance" in system and "Never words, never an inner thought" in system
    assert system == shots.SYSTEM  # static: byte-identical across scenes


def test_the_clip_schema_asks_for_a_performance_per_beat_and_a_position_per_subject():
    schema = get_schema().shot_schema()
    beat = schema["properties"]["beats"]["items"]["properties"]
    subject = schema["properties"]["subjects"]["items"]["properties"]
    assert "performance" in beat and "position" in subject
    assert "Never words" in beat["performance"]["description"]


def test_a_scene_without_a_reading_or_a_map_is_designed_exactly_as_before():
    store = store_for()
    llm = llms()
    run(store, llm, scene_ids=[store.scene_row["id"]])
    user = design_calls(llm)[0]["user"]
    assert "PERFORMANCE" not in user and "POSITIONS" not in user and "WHAT EACH PERSON WANTS" not in user


def test_the_rules_write_the_performance_from_the_reading_and_the_position_from_the_map():
    store = felt_store()
    run(store, scene_ids=[store.scene_row["id"]])  # no key: the rules design
    shot = call(store)
    performances = [b["performance"] for b in shot["ir"]["beats"]]
    assert any("Anudi's face receives it" in p for p in performances)
    assert shot["ir"]["subjects"][0]["position"].startswith("Anudi at the street")


def test_the_performance_reaches_the_video_prompt_and_the_voice_carries_what_the_speaker_wants():
    store = felt_store()
    llm = llms(scene_design=lambda s, u: {"shots": [
        {**e, "beats": [{**b, "performance": "keeps smiling a moment too long, then her eyes drop to the phone"}
                        for b in e["beats"]]} for e in dp([1, 2])["shots"]]})
    shot = call(store)
    store.frames[shot["id"]] = {"id": str(uuid4()), "shot_id": shot["id"], "pins": {}}
    run(store, llm, mode="prompt", shot_ids=[shot["id"]])
    prose = store.prompts[0]["prose"]
    assert "keeps smiling a moment too long, then her eyes drop to the phone" in prose
    assert any(c["label"].startswith("Performance written where the feeling turns") and c["tone"] == "pass"
               for c in store.prompts[0]["checks"])


def test_a_turn_with_no_performance_and_a_first_frame_set_elsewhere_are_free_problems():
    store = felt_store()
    run(store, llm := llms(), scene_ids=[store.scene_row["id"]])
    assert llm.calls
    from shot_producer.engine.model import production_input, scene_input

    canon = PHONE_CANON
    prod = production_input({"id": "p", "title": "t", "orientation": "horizontal", "settings": {}}, canon, None)
    scene = scene_input(store.scene_row, store.shots(store.scene_row["id"]), store.line_rows, canon, prod)
    second = scene.shots[1]
    ir = dp([2])["shots"][0]
    problems = critique.free_problems(second, ir, [c.id for c in second.seen], canon, scene)
    assert any(p.startswith("No performance in the beat at") for p in problems)
    # a first frame set at the street, where Anudi stands, is fine; one set at the stall is a jump
    ir["first_frame"]["setting"] = "the street outside the stall"
    assert not any(p.startswith("Position jump") for p in critique.free_problems(second, ir, [], canon, scene))
    ir["first_frame"]["setting"] = "the stall"
    ir["first_frame"]["composition"] = "Anudi at the stall"
    jumped = critique.free_problems(second, ir, [], canon, scene)
    assert any(p.startswith("Position jump") for p in jumped)
    ir["beats"] = [{**b, "performance": "her smile holds, then slips"} for b in ir["beats"]]
    assert not any(p.startswith("No performance") for p in critique.free_problems(second, ir, [], canon, scene))


def test_the_intent_agent_reads_the_reading_and_the_rules_take_purpose_and_beat_from_it():
    store = felt_store()
    llm = llms()
    run(store, llm, scene_ids=[store.scene_row["id"]])
    asked = next(c for c in llm.calls if c["schema"] == "shot_intent")
    assert "READING OF THE SCENE (decided before the shots):" in asked["user"]
    assert "WHERE EVERYONE IS (the staging map):" in asked["user"]
    assert "purpose and emotional_beat COME FROM IT" in asked["system"]
    # the free rules
    store = felt_store()
    run(store, scene_ids=[store.scene_row["id"]])
    second = call(store)["intent"]
    assert second["by"] == "rules" and second["emotional_beat"] == "joy to dread"
    assert "where the feeling turns" in second["purpose"] and "Anudi wanting to hide it" in second["purpose"]
    first = sorted(store.shot_rows.values(), key=lambda s: s["number"])[0]["intent"]
    assert first["emotional_beat"] == "warm, uneasy"  # no turn in it: the scene's tone


def test_the_ledger_carries_where_everyone_was_left_to_the_next_shot():
    store = felt_store()
    run(store, scene_ids=[store.scene_row["id"]])
    from shot_producer.engine.model import production_input, scene_input

    prod = production_input({"id": "p", "title": "t", "orientation": "horizontal", "settings": {}}, PHONE_CANON, None)
    scene = scene_input(store.scene_row, store.shots(store.scene_row["id"]), store.line_rows, PHONE_CANON, prod)
    ledger = ContinuityLedger(prod.cast)
    ledger.observe(scene.id, scene.shots[0], scene.shots[0].row.get("ir") or {})
    assert "S01 left everyone here: Kasun at the stall" in ledger.scene_block(scene.id)
    assert feeling.positions_text(scene.shots[0].feeling.end).startswith("Kasun at the stall")


def test_an_out_of_date_reading_still_gives_its_holds_but_not_numbered_notes():
    store = felt_store()
    scene = store.scene_row
    store.scene_row = {**scene, "script": [{"kind": "action", "text": "A new first line.", "line_id": None},
                                           *scene["script"]]}
    from shot_producer.engine.model import production_input, scene_input

    prod = production_input({"id": "p", "title": "t", "orientation": "horizontal", "settings": {}}, PHONE_CANON, None)
    items = sceneplan.scene_items(store.scene_row, store.line_rows)
    r = rd.SceneReading.of(store.scene_row)
    assert r is not None and r.stale(sceneplan.items_for(store.scene_row["script"], store.line_rows), 1)
    assert [at for _, at in r.resolved(items)] == [6]  # the hold followed its block
    built = scene_input(store.scene_row, [], store.line_rows, PHONE_CANON, prod)
    assert built.reading is not None
    got = feeling.feeling_for(built.reading, None, items, items[2:7], [(0, 4), (4, 8)], CAST)
    assert got.person_wants == {}  # unit numbers are not trusted once the script moved
    assert any("receives it" in n for notes in got.beat_notes.values() for n in notes)
