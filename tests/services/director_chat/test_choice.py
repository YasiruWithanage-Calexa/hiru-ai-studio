"""Choosing a side in a disagreement: the stored edit finds its shot by id and is applied."""
from __future__ import annotations

from uuid import UUID, uuid4

from director_chat.app.handler import handle_choice
from director_chat.engine import choice, turn

from contracts.director import ChoicePayload
from tests.services.director_chat.conftest import PID, DirectorLLM, FakeStore, fixture_scene
from tests.services.director_chat.test_turn import plan_answer, run

ACTOR = uuid4()


def store0() -> FakeStore:
    return FakeStore(*fixture_scene(0))


def choose(store: FakeStore, ops: list[dict]) -> choice.ChoiceResult:
    return choice.apply_choice(ChoicePayload(production_id=PID, scene_id=UUID(store.scene_row["id"]),
                                             actor_user_id=ACTOR, ops=ops), store)


def collision(store: FakeStore) -> dict:
    """Sound and cinematography both set S01's sound mode; sound owns it."""
    responders = {
        "turn_plan": lambda s, u: plan_answer("craft", tasks=[
            {"agent": "cinematography", "shots": [1], "instruction": "x"},
            {"agent": "sound", "shots": [1], "instruction": "y"}]),
        "cinematography_ops": lambda s, u: {"ops": [{"op": "set", "shot": 1, "field": "sound_mode",
                                                     "value": "music_only"}], "note": "Let music carry it."},
        "sound_ops": lambda s, u: {"ops": [{"op": "set", "shot": 1, "field": "sound_mode", "value": "silent"}],
                                   "note": "Let the dawn be silent."},
    }
    run(store, "quieter", DirectorLLM(responders))
    return next(b for b in store.message_rows[-1]["blocks"] if b["kind"] == "disagreement")


def test_a_disagreement_keeps_both_edits_pinned_to_the_shot_and_marks_the_one_that_landed():
    store = store0()
    first = store.shots(PID)[0]["id"]
    block = collision(store)
    assert block["title"] == "Two views on S01 sound mode" and "actions" not in block
    sound, cine = block["positions"]
    assert sound["who"] == "Sound" and sound["applied"] and sound["change"] == "S01 sound mode → silent"
    assert cine["who"] == "Cinematography" and not cine["applied"] and cine["text"] == "Let music carry it."
    assert cine["ops"] == [{"op": "set", "field": "sound_mode", "value": "music_only", "shot_id": first}]


def test_choosing_the_other_side_applies_its_edit_saves_and_audits():
    store = store0()
    cine = collision(store)["positions"][1]
    result = choose(store, cine["ops"])
    assert result.applied and result.summary == "Applied: S01 sound mode → music_only."
    assert store.saved[-1]["shots"][0]["sound_mode"] == "music_only"
    assert store.audits[-1]["action"] == "scene.director_choice"
    assert store.audits[-1]["actor_user_id"] == str(ACTOR)


def test_the_edit_follows_its_shot_when_numbers_move():
    store = store0()
    third = store.shots(PID)[2]["id"]
    run(store, "remove shot 1")  # S03 is now S02
    result = choose(store, [{"op": "set", "field": "framing", "value": "CU", "shot_id": third}])
    shot = next(s for s in store.saved[-1]["shots"] if s["id"] == third)
    assert result.applied and shot["framing"] == "CU" and shot["number"] == 2


def test_a_shot_that_is_gone_or_a_locked_scene_changes_nothing():
    store = store0()
    gone = choose(store, [{"op": "set", "field": "framing", "value": "CU", "shot_id": str(uuid4())}])
    assert not gone.applied and gone.summary == choice.GONE
    store.scene_row["status"] = "approved"
    first = store.shots(PID)[0]["id"]
    locked = choose(store, [{"op": "set", "field": "framing", "value": "CU", "shot_id": first}])
    assert not locked.applied and "approved and locked" in locked.summary
    assert not store.saved


def test_pin_and_unpin_round_trip():
    op = {"op": "insert", "after_shot": 2, "description": "Kamala reacts", "framing": "CU", "by": "cinematography"}
    pinned = turn.pin(op, ["a", "b", "c"])
    assert pinned == {"op": "insert", "description": "Kamala reacts", "framing": "CU", "after_shot_id": "b"}
    assert turn.unpin(pinned, ["b", "c"]) == {"op": "insert", "description": "Kamala reacts", "framing": "CU",
                                              "after_shot": 1}
    assert turn.unpin(pinned, ["a", "c"]) is None
    assert turn.pin({"op": "set", "shot": 1}, ["new1"]) == {}  # made this turn: no id to pin to


def test_the_handler_refuses_a_bad_choice_payload():
    assert handle_choice({"kind": "choice", "ops": []})[1] == 400
