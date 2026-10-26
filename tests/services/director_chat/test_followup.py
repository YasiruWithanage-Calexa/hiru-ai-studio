"""Phase 0 of Director Chat v2: the S02 conversation. "Update S02 with that" answers the director's
last suggestion, a refusal is never raw internals, and a reply never points at a card that is not
there (plan/2026-10-26)."""
from __future__ import annotations

import pytest
from director_chat.engine import kernel as kernel_module
from director_chat.engine import proposals, refusals, turn

from tests.services.director_chat.conftest import DirectorLLM, FakeStore
from tests.services.director_chat.test_options import answer, op
from tests.services.director_chat.test_turn import plan_answer, run, store0

ADVICE = "Open S02 on a wide so the road gap reads, and let Anudi step out of the family car."
WIDE = {"label": "Open S02 wide", "detail": "The road gap reads.", "prompt": "",
        "ops": [op(op="set", shot=2, field="framing", value="WIDE")]}


def director(text: str = "", blocks: list[dict] | None = None, id: str = "d1") -> dict:
    return {"id": id, "kind": "director", "speaker": "CT", "text": "",
            "blocks": blocks if blocks is not None else [{"kind": "text", "text": text}]}


def with_advice(store: FakeStore, text: str = ADVICE) -> FakeStore:
    store.history = [{"id": "u0", "kind": "user", "speaker": "Dee", "text": "Anudi renders on the three-wheeler",
                      "blocks": []}, director(text)]
    return store


def follow_llm(*options: dict, **responders) -> DirectorLLM:
    # The conductor reads "update S02 with that" as an edit but has nothing to write.
    return DirectorLLM({"turn_plan": lambda s, u: plan_answer("edit"),
                        "chat_options": lambda s, u: answer(*options), **responders})


# ── reading a follow-up ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("message", ["update S02 with that", "Update @S02 with that please", "yes", "Yes, do it",
                                     "do that", "apply it", "go ahead", "ok do that for S04", "use this",
                                     "fix the frame using that"])
def test_short_answers_to_advice_are_follow_ups(message: str):
    assert proposals.refers_back(message), message


@pytest.mark.parametrize("message", ["make shot 2 eight seconds", "what do you think?", "that is too long",
                                     "update S02 so Anudi stands on the pavement", "no", "how long is it"])
def test_other_messages_are_not(message: str):
    assert not proposals.refers_back(message), message


def test_the_latest_advice_is_the_directors_last_message():
    card = director(blocks=[{"kind": "text", "text": "Two ways to go."},
                            {"kind": "options", "question": "", "chosen": None,
                             "options": [{"label": "A", "ops": [{"op": "retime"}], "prompt": ""}]}])
    assert proposals.latest_advice([director(ADVICE), card]) == proposals.Advice("card", "Two ways to go.")
    chosen = director(blocks=[{"kind": "options", "chosen": 0, "options": [{"label": "A", "ops": [{}]}]}])
    assert proposals.latest_advice([director(ADVICE), chosen]) is None  # a choice made leaves nothing open
    assert proposals.latest_advice([director(ADVICE)]) == proposals.Advice("text", ADVICE)
    assert proposals.latest_advice([director("Done."), {"kind": "user", "text": "hi"}]) is None
    assert proposals.latest_advice([]) is None


def test_a_reply_may_point_at_a_card_only_when_there_is_one():
    text = "Open on a wide. You can apply it below. The scene stays under the envelope."
    assert proposals.guard_reply(text, has_card=True) == text
    assert proposals.guard_reply(text, has_card=False) == "Open on a wide. The scene stays under the envelope."
    assert proposals.guard_reply("Choose Apply on the card.", has_card=False) == ""
    assert proposals.guard_reply("It runs below the envelope.", has_card=False) == "It runs below the envelope."


# ── the turn ───────────────────────────────────────────────────────────────────────────────


def test_update_s02_with_that_becomes_one_card_to_apply():
    store = with_advice(store0())
    llm = follow_llm(WIDE)
    events = run(store, "update S02 with that", llm)
    assert not store.saved  # nothing is applied unseen
    message = store.message_rows[-1]
    card = next(b for b in message["blocks"] if b["kind"] == "options")
    assert [o["label"] for o in card["options"]] == ["Open S02 wide", "Keep it as it is"]
    assert card["options"][0]["ops"][0]["shot_id"] and card["options"][0]["ops"][0]["field"] == "framing"
    assert next(d for e, d in events if e == "done")["lane"] == "options"
    conducts = [c for c in llm.calls if c["phase"] == "director.conduct"]
    assert len(conducts) == 2 and "<again>" not in conducts[0]["user"] and "<again>" in conducts[1]["user"]
    proposal = next(c for c in llm.calls if c["phase"] == "director.options")
    assert ADVICE in proposal["user"] and "ONE option" in proposal["user"]


def test_a_follow_up_without_advice_is_just_answered():
    store = store0()  # no history
    run(store, "yes", follow_llm(WIDE))
    assert not store.saved
    assert all(b["kind"] != "options" for b in store.message_rows[-1]["blocks"])


def test_advice_that_cannot_be_made_into_a_change_says_so_plainly():
    store = with_advice(store0())
    nothing = op(op="set", shot=40, field="framing", value="WIDE")
    llm = follow_llm({"label": "Use shot 40", "detail": "", "prompt": "", "ops": [nothing]})
    run(store, "do that", llm)
    message = store.message_rows[-1]
    assert message["blocks"][0]["text"] == turn.NOT_TURNED
    assert [b["kind"] for b in message["blocks"]] == ["text"]  # no card, so nothing promised below


def test_an_open_card_stays_the_way_to_apply():
    store = store0()
    store.history = [director(blocks=[{"kind": "text", "text": "Two ways to go."},
                                      {"kind": "options", "chosen": None,
                                       "options": [{"label": "A", "ops": [{"op": "retime"}], "prompt": ""}]}])]
    run(store, "yes", follow_llm(WIDE))
    assert store.message_rows[-1]["blocks"][0]["text"] == turn.WAITING_ON_CARD
    assert all(b["kind"] != "options" for b in store.message_rows[-1]["blocks"])


def test_a_role_that_cannot_change_the_shot_list_gets_no_card():
    store = with_advice(store0())
    run(store, "update S02 with that", follow_llm(WIDE), can_edit=False)
    assert "can comment but not change" in store.message_rows[-1]["blocks"][0]["text"]
    assert all(b["kind"] != "options" for b in store.message_rows[-1]["blocks"])


def test_a_model_that_writes_nothing_is_asked_once_more_then_accepted():
    store = store0()
    llm = DirectorLLM({"turn_plan": lambda s, u: plan_answer("edit")})
    run(store, "make the scene better somehow, with more of the tension we talked about", llm)
    assert len([c for c in llm.calls if c["phase"] == "director.conduct"]) == 2
    assert not store.saved and store.message_rows[-1]["ops"] == []


def test_the_second_ask_can_make_the_change():
    store = store0()
    answers = iter([plan_answer("edit"), plan_answer("edit", ops=[{"op": "retime", "shot": 2, "seconds": 8}])])
    llm = DirectorLLM({"turn_plan": lambda s, u: next(answers)})
    run(store, "shot two, eight seconds, as discussed", llm)
    assert store.saved[-1]["shots"][1]["duration_s"] == 8


def test_a_reply_that_points_at_a_missing_card_is_corrected():
    store = store0()
    llm = DirectorLLM({"turn_plan": lambda s, u: plan_answer("chat")},
                      reply="Open S02 on a wide so the road gap reads. You can apply it below.")
    run(store, "how should S02 open?", llm)
    text = store.message_rows[-1]["blocks"][0]["text"]
    assert "below" not in text and text.startswith("Open S02 on a wide")


def test_a_reply_about_nothing_but_a_card_falls_back_to_the_plain_reply():
    store = store0()
    llm = DirectorLLM({"turn_plan": lambda s, u: plan_answer("chat")}, reply="Choose Apply on the card.")
    run(store, "how should S02 open?", llm)
    text = store.message_rows[-1]["blocks"][0]["text"]
    assert "card" not in text and "scene runs" in text


def test_the_reply_model_reads_the_ledger_last():
    store = store0()
    llm = DirectorLLM({"turn_plan": lambda s, u: plan_answer("edit", ops=[{"op": "retime", "shot": 2, "seconds": 8}])})
    run(store, "make shot 2 eight seconds", llm)
    prompt = llm.streamed[-1][1]["content"]
    assert prompt.index("<message>") < prompt.index("<turn>") and prompt.rstrip().endswith("</turn>")
    assert "Applied: S02 is now 8 s" in prompt


# ── refusals read as sentences ─────────────────────────────────────────────────────────────

MALFORMED = [
    {"op": "block.set", "block": 1, "field": "text"},  # no value: "text takes text" before
    {"op": "block.set", "block": 1, "field": "text", "value": None},
    {"op": "block.insert", "block": 1, "kind": "action"},
    {"op": "set", "shot": 1, "field": "title"},
    {"op": "set", "shot": 1, "field": "framing", "value": ["WIDE"]},
    {"op": "beat.set", "shot": 1, "beat": 0, "field": "camera", "value": {"a": 1}},
    {"op": "insert", "after_shot": 1},
    {"op": "retime", "shot": "abc", "seconds": 6},
    {"op": "retime", "shot": 1, "seconds": None},
    {"op": "stage.set", "shot": 2, "who": "Anudi"},
    {"op": "camera.set", "shot": 2, "field": "lens", "value": "24mm"},
    {"op": "line.edit", "line": 1, "text": "x"},
    {"op": None},
    "set shot 1 wide",
    {},
]


def test_every_malformed_operation_is_refused_in_words_a_person_can_read():
    k = turn.kernel_for(*_scene(store0()), None, [])
    result = k.apply(MALFORMED, by="you", respect_locks=False)
    assert not result.applied and len(result.rejected) == len(MALFORMED)
    for r in result.rejected:
        assert not refusals.INTERNAL.search(r["reason"]), r
        assert r["reason"] != refusals.FALLBACK, f"{r['op']} fell back to the generic sentence"


def _scene(store: FakeStore):
    return store.scene_row, store.line_rows, store.shot_rows


def test_the_s02_refusal_never_reaches_the_reply_as_internals():
    store = store0()
    bad = [{"op": "block.set", "block": 1, "field": "text"}, {"op": "stage.set", "shot": 2}]
    llm = DirectorLLM({"turn_plan": lambda s, u: plan_answer("edit", ops=bad)})
    run(store, "update S02 with that", llm)
    prompt = llm.streamed[-1][1]["content"]
    refused = prompt.split("Refused:")[1].split("</turn>")[0]
    assert not refusals.INTERNAL.search(refused) and "takes text" not in prompt
    plain = store0()
    run(plain, "x", DirectorLLM(enabled=False))  # rules mode shares the same kernel and the same sentences
    assert not refusals.INTERNAL.search(plain.message_rows[-1]["blocks"][0]["text"])


def test_a_stray_validation_message_is_replaced():
    assert refusals.for_person("text takes text") == refusals.FALLBACK
    assert refusals.for_person("shots have no 'None' field") == refusals.FALLBACK
    assert refusals.for_person("there is no shot 9") == "there is no shot 9"
    assert kernel_module.OpError  # the kernel still raises it; only what is recorded passes through the filter


# ── "have you applied it?" is answered from the record ────────────────────────────────────


def test_a_card_the_person_chose_is_in_the_history_the_models_read():
    store = store0()
    store.history = [director(blocks=[
        {"kind": "text", "text": "Pick the pre-insert."},
        {"kind": "options", "question": "How should S02 play?", "chosen": 0,
         "outcome": "Applied: new OTS shot after S01.",
         "options": [{"label": "Pre-insert: seated in car", "ops": [{"op": "insert"}]}]}])]
    llm = DirectorLLM({"turn_plan": lambda s, u: plan_answer("chat")})
    run(store, "have you applied it", llm)
    seen = llm.tool_rounds[-1][1]["content"]
    assert 'The person chose "Pre-insert: seated in car". Applied: new OTS shot after S01.' in seen
    assert "Applied this turn: nothing" in seen and "Changes made earlier" in seen


def test_a_card_not_chosen_yet_says_nothing_was_applied():
    store = store0()
    store.history = [director(blocks=[{"kind": "text", "text": "Two ways."},
                                      {"kind": "options", "chosen": None,
                                       "options": [{"label": "A", "ops": [{"op": "insert"}]}]}])]
    llm = DirectorLLM({"turn_plan": lambda s, u: plan_answer("chat")})
    run(store, "have you applied it", llm)
    assert "no choice made yet, nothing applied: A" in llm.tool_rounds[-1][1]["content"]
