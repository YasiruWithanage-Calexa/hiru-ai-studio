"""The options lane: the lead offers choices, each tried on a copy of the scene, none applied."""
from __future__ import annotations

from uuid import UUID, uuid4

from director_chat.engine import choice

from contracts.director import ChoicePayload, OptionsBlock
from tests.services.director_chat.conftest import PID, DirectorLLM, FakeStore, fixture_scene
from tests.services.director_chat.test_turn import plan_answer, run

NULLS = {k: None for k in ("shot", "field", "value", "seconds", "at_block", "end_block", "link", "beat",
                           "after_shot", "description", "framing", "title")}


def op(**fields) -> dict:
    return {**NULLS, **fields}


def answer(*options: dict) -> dict:
    return {"question": "How should S02 play?", "options": list(options)}


PUSH_IN = {"label": "Push in to a tight CU", "detail": "Closer as he arrives.", "prompt": "",
           "ops": [op(op="set", shot=2, field="framing", value="CU"),
                   op(op="beat.set", shot=2, beat=0, field="camera", value="slow push in")]}
LONGER = {"label": "Let it breathe", "detail": "Hold the moment.", "prompt": "",
          "ops": [op(op="retime", shot=2, seconds=8)]}
TONE = {"label": "Play it warmer", "detail": "Softer light, kinder eyes.", "ops": [],
        "prompt": "Make S02 warmer in tone."}
BROKEN = {"label": "Use shot 40", "detail": "", "prompt": "",
          "ops": [op(op="set", shot=40, field="framing", value="CU")]}


def options_turn(store: FakeStore, *options: dict) -> tuple[list, DirectorLLM]:
    llm = DirectorLLM({"turn_plan": lambda s, u: plan_answer("options"),
                       "chat_options": lambda s, u: answer(*options)})
    return run(store, "give me options for S02", llm), llm


def test_options_are_offered_tried_on_a_copy_and_nothing_is_applied():
    store = FakeStore(*fixture_scene(0))
    second = store.shots(PID)[1]["id"]
    events, llm = options_turn(store, PUSH_IN, LONGER, TONE, BROKEN)
    assert not store.saved and "plan" not in [e for e, _ in events]  # offered, not applied
    message = store.message_rows[-1]
    assert [b["kind"] for b in message["blocks"]] == ["text", "options"]
    block = OptionsBlock.model_validate(message["blocks"][1])
    assert block.question == "How should S02 play?"
    assert [o.label for o in block.options] == ["Push in to a tight CU", "Let it breathe", "Play it warmer"]
    push, longer, tone = block.options
    assert push.ops == [{"op": "set", "field": "framing", "value": "CU", "shot_id": second},
                        {"op": "beat.set", "beat": 0, "field": "camera", "value": "slow push in", "shot_id": second}]
    assert push.change == "S02 framing → CU; S02 beat 1: camera" and not push.prompt
    assert "→" in longer.impact and longer.impact.startswith("Scene ")
    assert tone.ops == [] and tone.prompt == "Make S02 warmer in tone."
    assert next(d for e, d in events if e == "done")["lane"] == "options"
    reply_prompt = llm.streamed[-1][1]["content"]
    assert "Do not list" in reply_prompt and "Push in to a tight CU" in reply_prompt


def test_a_chosen_option_applies_through_the_choice_path():
    store = FakeStore(*fixture_scene(0))
    options_turn(store, PUSH_IN, LONGER)
    push = store.message_rows[-1]["blocks"][1]["options"][0]
    result = choice.apply_choice(ChoicePayload(production_id=PID, scene_id=UUID(store.scene_row["id"]),
                                               actor_user_id=uuid4(), ops=push["ops"]), store)
    assert result.applied and store.saved[-1]["shots"][1]["framing"] == "CU"


def test_with_fewer_than_two_workable_options_it_is_answered_as_a_question():
    store = FakeStore(*fixture_scene(0))
    events, llm = options_turn(store, PUSH_IN, BROKEN)
    assert [b["kind"] for b in store.message_rows[-1]["blocks"]] == ["text"]
    assert next(d for e, d in events if e == "done")["lane"] == "chat"
    assert llm.tool_rounds  # the question path, with its read tools


def test_without_a_key_there_are_no_options():
    store = FakeStore(*fixture_scene(0))
    run(store, "give me options for S02")
    assert [b["kind"] for b in store.message_rows[-1]["blocks"]] == ["text"]
