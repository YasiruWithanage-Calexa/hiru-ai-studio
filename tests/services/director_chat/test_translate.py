"""Phase 4 of plan/2026-11-01c: the translator agent. The script stays in the language it was written in; only when
the person asks for the dialogue in another language does the translator write it, as a card that shows every line
before and after, and the original words are kept as each line's source."""
from __future__ import annotations

import pytest
from director_chat.engine import choice, conductor, translate, turn
from director_chat.engine import kernel as kernel_mod
from director_chat.engine.kernel import ScenePlanKernel

from contracts import director_capabilities as caps
from contracts.director import ChoicePayload
from tests.services.director_chat.conftest import PID, DirectorLLM, FakeStore
from tests.services.director_chat.test_pending import say
from tests.services.director_chat.test_turn import ACTOR, plan_answer, run, store0

EN = ["Mother, I am back.", "Sit down and eat."]
SI = ["අම්මේ, මම ආපහු ආවා.", "වාඩි වෙලා කන්න."]
TA = "அம்மா, நான் திரும்பி வந்துட்டேன்."
ASK = "put all the dialogue in Sinhala"


def english_store() -> FakeStore:
    store = store0()
    for row, text in zip(store.line_rows, EN, strict=True):
        row["text"] = text
    return store


def conduct(code: str = "si", language: str = "Sinhala", style: str = "", shots: list[int] | None = None) -> dict:
    return {**plan_answer("translate"), "cannot": None,
            "translate": {"language": language, "code": code, "style": style, "shots": shots or []}}


def translator(store: FakeStore, texts: list[str], *, ids: list[int] | None = None):
    """A responder for the translator: the store's lines (or the nth ones) answered with `texts`."""
    rows = store.line_rows
    chosen = [rows[i] for i in ids] if ids is not None else rows
    return lambda s, u: {"lines": [{"line_id": r["id"], "text": t} for r, t in zip(chosen, texts, strict=True)]}


def llm_for(store: FakeStore, texts: list[str] = SI, **plan) -> DirectorLLM:
    return DirectorLLM({"turn_plan": lambda s, u: conduct(**plan), "dialogue_translation": translator(store, texts)})


def kernel_of(store: FakeStore) -> ScenePlanKernel:
    return turn.kernel_for(store.scene_row, store.line_rows, store.shot_rows, None, store.canon(PID))


def card_of(store: FakeStore) -> dict:
    return next(b for b in store.message_rows[-1]["blocks"] if b["kind"] == "options")


def apply_card(store: FakeStore, option: int = 0) -> choice.ChoiceResult:
    opt = card_of(store)["options"][option]
    return choice.apply_choice(ChoicePayload(production_id=PID, scene_id=store.scene_row["id"], actor_user_id=ACTOR,
                                             can_edit_script=True, ops=opt["ops"], intent=opt.get("intent", "")), store)


# ── the default is to leave the script alone ─────────────────────────────────────────────────


def test_an_ordinary_edit_never_calls_the_translator_and_the_script_keeps_its_language():
    store = english_store()
    llm = DirectorLLM({"turn_plan": lambda s, u: plan_answer("edit", ops=[{"op": "retime", "shot": 2, "seconds": 8}]),
                       "dialogue_translation": translator(store, SI)})
    run(store, "make shot 2 eight seconds", llm)
    assert not any(c["schema"] == "dialogue_translation" for c in llm.calls)
    assert [ln["text"] for ln in store.line_rows] == EN


def test_a_question_about_the_language_is_answered_not_translated():
    store = english_store()
    llm = DirectorLLM({"turn_plan": lambda s, u: plan_answer("chat")}, reply="They are in English.")
    run(store, "Why are the lines in English?", llm)
    assert not any(c["schema"] == "dialogue_translation" for c in llm.calls) and not store.saved


# ── the card ───────────────────────────────────────────────────────────────────────────────


def test_a_request_stages_one_card_with_every_line_before_and_after_and_saves_nothing():
    store = english_store()
    events = run(store, ASK, llm_for(store))
    assert events[-1][1]["lane"] == "options" and not store.saved  # nothing is saved until a person applies it
    assert [ln["text"] for ln in store.line_rows] == EN
    card = card_of(store)
    apply_option, keep = card["options"]
    assert card["question"] == "Translate 2 spoken lines to Sinhala?" and keep["ops"] == []
    assert apply_option["label"] == "Translate 2 spoken lines to Sinhala" and apply_option["intent"] == "dialogue.si"
    assert apply_option["lines"] == [
        {"line_id": store.line_rows[0]["id"], "shot": 2, "speaker": "Nimal", "was": EN[0], "now": SI[0]},
        {"line_id": store.line_rows[1]["id"], "shot": 4, "speaker": "Kamala", "was": EN[1], "now": SI[1]}]
    assert all(op["op"] == "block.set" and op["translated_to"] == "si" and op["line_id"] for op in apply_option["ops"])
    assert "not changed the script yet" in store.message_rows[-1]["blocks"][0]["text"]


def test_the_translator_gets_the_language_the_style_the_speakers_and_the_production_rules():
    store = english_store()
    store.memory_rows.append({"kind": "decision", "text": "Kamala always speaks formally."})
    llm = llm_for(store, [TA, TA], code="ta", language="Tamil", style="colloquial")
    run(store, "translate the dialogue to Tamil, colloquial", llm)
    call = next(c for c in llm.calls if c["schema"] == "dialogue_translation")
    assert call["tier"] == "high" and call["system"] == translate.SYSTEM
    assert '<target language="Tamil" code="ta">' in call["user"] and "<style>colloquial</style>" in call["user"]
    assert "Kamala always speaks formally." in call["user"] and '"speaker": "Kamala"' in call["user"]
    assert EN[0] in call["user"] and "never instructions" in call["system"]


def test_the_person_names_the_language_so_it_need_not_be_sinhala():
    store = english_store()
    run(store, "translate the dialogue to Tamil", llm_for(store, [TA, TA], code="ta", language="Tamil"))
    card = card_of(store)
    assert card["question"] == "Translate 2 spoken lines to Tamil?" and card["options"][0]["intent"] == "dialogue.ta"


def test_a_language_that_cannot_be_checked_is_still_translated_and_just_not_verified():
    store = english_store()
    french = ["Maman, je suis rentré.", "Assieds-toi et mange."]
    run(store, "put the dialogue in French", llm_for(store, french, code="", language="French"))
    apply_option = card_of(store)["options"][0]
    assert apply_option["label"] == "Translate 2 spoken lines to French" and "intent" not in apply_option
    assert [row["now"] for row in apply_option["lines"]] == french
    assert {op["translated_to"] for op in apply_option["ops"]} == {"French"}


def test_a_scope_of_one_shot_translates_only_its_lines():
    store = english_store()
    llm = DirectorLLM({"turn_plan": lambda s, u: conduct(shots=[2]),
                       "dialogue_translation": translator(store, [SI[0]], ids=[0])})
    run(store, "translate S02 to Sinhala", llm)
    (row,) = card_of(store)["options"][0]["lines"]
    assert row["shot"] == 2 and row["now"] == SI[0]
    call = next(c for c in llm.calls if c["schema"] == "dialogue_translation")
    assert EN[0] in call["user"] and EN[1] not in call["user"]


def test_a_one_shot_translation_is_judged_on_its_own_lines_when_applied():
    store = english_store()
    llm = DirectorLLM({"turn_plan": lambda s, u: conduct(shots=[2]),
                       "dialogue_translation": translator(store, [SI[0]], ids=[0])})
    run(store, "translate S02 to Sinhala", llm)
    result = apply_card(store)
    assert result.applied and "Goal reached: every translated line is in Sinhala." in result.summary
    assert "Goal NOT reached" not in result.summary and store.line_rows[1]["text"] == EN[1]


def test_a_one_shot_translation_saves_rows_postgrest_accepts():
    """Only one line has a source after it: every row of the bulk write still has the same keys."""
    from director_chat.runtime.store import Store

    store = english_store()
    llm = DirectorLLM({"turn_plan": lambda s, u: conduct(shots=[2]),
                       "dialogue_translation": translator(store, [SI[0]], ids=[0])})
    run(store, "translate S02 to Sinhala", llm)
    apply_card(store)
    written = store.saved[-1]["lines"]
    assert any("source_text" in r for r in written) and not all("source_text" in r for r in written)

    class Rest:
        def __init__(self) -> None:
            self.upserts: list[tuple[str, list[dict]]] = []

        def upsert(self, table: str, rows: list[dict]) -> None:
            self.upserts.append((table, rows))

        def delete(self, *a: object) -> None: ...
        def patch(self, *a: object) -> None: ...

    rest = Rest()
    Store(rest).save_plan(store.scene_row["id"], [], [], written, {})  # type: ignore[arg-type]
    ((table, rows),) = rest.upserts
    assert table == "dialogue_lines" and len({frozenset(r) for r in rows}) == 1
    untranslated = next(r for r in rows if r["id"] == store.line_rows[1]["id"])
    assert untranslated["source_text"] is None and untranslated["source_lang"] is None


def test_asking_again_after_the_translator_failed_tries_again():
    store = english_store()

    def broken(s, u):
        raise RuntimeError("down")

    say(store, ASK, DirectorLLM({"turn_plan": lambda s, u: conduct(), "dialogue_translation": broken}))
    say(store, ASK, llm_for(store))
    assert card_of(store)["options"][0]["intent"] == "dialogue.si"


def test_the_language_can_come_from_an_earlier_message_when_this_one_only_complains():
    store = english_store()
    store.history = [{"id": "u1", "kind": "user", "text": "i need all dialogues in Sinhala language", "blocks": []}]
    plan = conductor.by_rules("no still dialogues are in english", split_points={}, translator=True,
                              earlier=["i need all dialogues in Sinhala language"])
    assert plan.lane == "translate" and plan.translate and plan.translate["code"] == "si"


# ── applying it ────────────────────────────────────────────────────────────────────────────


def test_applying_the_card_saves_the_translation_and_keeps_the_original_as_the_source():
    store = english_store()
    run(store, ASK, llm_for(store))
    result = apply_card(store)
    assert result.applied and "Changed dialogue on 2 lines." in result.summary and "Goal reached" in result.summary
    rows = {ln["id"]: ln for ln in store.saved[-1]["lines"]}
    first, second = (rows[ln["id"]] for ln in store.line_rows)
    assert (first["text"], second["text"]) == tuple(SI)
    assert (first["source_text"], first["source_lang"]) == (EN[0], "en")
    assert (second["source_text"], second["source_lang"]) == (EN[1], "en")
    assert store.audits[-1]["action"] == "scene.director_choice"


def test_a_second_translation_keeps_the_first_original_not_the_intermediate_one():
    store = english_store()
    run(store, ASK, llm_for(store))
    apply_card(store)
    run(store, "translate the dialogue to Tamil", llm_for(store, [TA, TA], code="ta", language="Tamil"))
    apply_card(store)
    assert {ln["source_text"] for ln in store.line_rows} == set(EN)
    assert {ln["source_lang"] for ln in store.line_rows} == {"en"}
    assert all(caps.script_of(ln["text"]) == "ta" for ln in store.line_rows)


def test_going_back_to_the_source_language_needs_no_translator_call():
    store = english_store()
    run(store, ASK, llm_for(store))
    apply_card(store)
    llm = DirectorLLM({"turn_plan": lambda s, u: conduct(code="en", language="English")})  # no translator answer
    run(store, "put the dialogue back to English", llm)
    assert not any(c["schema"] == "dialogue_translation" for c in llm.calls)
    card = card_of(store)
    assert [row["now"] for row in card["options"][0]["lines"]] == EN
    apply_card(store)
    assert [ln["text"] for ln in store.line_rows] == EN


def test_a_line_someone_changed_since_the_card_was_shown_is_not_overwritten():
    store = english_store()
    run(store, ASK, llm_for(store))
    store.line_rows[0]["text"] = "Mother, I have come home."
    result = apply_card(store)
    assert not result.applied and result.summary == choice.GONE and not store.saved


def test_a_translation_that_makes_a_line_longer_is_reported_per_shot_never_trimmed():
    store = english_store()
    long_si = " ".join(["අම්මේ"] * 40)
    run(store, ASK, llm_for(store, [long_si, SI[1]]))
    result = apply_card(store)
    assert result.applied
    assert next(ln["text"] for ln in store.saved[-1]["lines"] if ln["id"] == store.line_rows[0]["id"]) == long_si


# ── what the translator may not do ─────────────────────────────────────────────────────────


def test_the_card_is_not_shown_to_a_role_without_the_script():
    store = english_store()
    llm = llm_for(store)
    run(store, ASK, llm, can_edit=True, can_edit_script=False)
    text = store.message_rows[-1]["blocks"][0]["text"]
    assert "can change shots but not the script" in text and not any(c["schema"] == "dialogue_translation"
                                                                    for c in llm.calls)
    assert not [b for b in store.message_rows[-1]["blocks"] if b["kind"] == "options"] and not store.saved


def test_the_kernel_lets_the_translator_write_only_a_marked_translation():
    k = kernel_of(english_store())
    marked = {"op": "block.set", "block": 1, "field": "text", "value": SI[0], "translated_to": "si"}
    plain = {"op": "block.set", "block": 1, "field": "text", "value": SI[0]}
    assert k.apply([plain], by=kernel_mod.TRANSLATOR).rejected  # an unmarked rewrite is not a translation
    assert k.apply([marked], by="cinematography").rejected  # and nobody else may write the words
    assert k.apply([{"op": "canon.add", "shot": 2, "value": "Kamala", "translated_to": "si"}],
                   by=kernel_mod.TRANSLATOR).rejected
    done = k.apply([marked], by=kernel_mod.TRANSLATOR)
    assert done.applied and not done.rejected
    assert k.items[1]["source_text"] == EN[0] and k.items[1]["source_lang"] == "en"


def test_a_translator_that_fails_changes_nothing_and_says_so():
    store = english_store()

    def broken(s, u):
        raise RuntimeError("down")

    run(store, ASK, DirectorLLM({"turn_plan": lambda s, u: conduct(), "dialogue_translation": broken}))
    text = store.message_rows[-1]["blocks"][0]
    assert "could not translate" in text["text"] and "Nothing was changed" in text["text"] and text["advice"] is False
    assert not store.saved and not [b for b in store.message_rows[-1]["blocks"] if b["kind"] == "options"]


def test_a_translation_that_comes_back_in_the_wrong_script_is_left_out_not_shown_as_done():
    store = english_store()
    run(store, ASK, llm_for(store, ["Mother, I'm home.", SI[1]]))
    (row,) = card_of(store)["options"][0]["lines"]
    assert row["now"] == SI[1]  # only the line that really came back in Sinhala
    assert "Left out: Nimal's line did not come back in Sinhala" in card_of(store)["options"][0]["detail"]


def test_when_nothing_came_back_right_the_reply_says_so_and_there_is_no_card():
    store = english_store()
    run(store, ASK, llm_for(store, EN))
    text = store.message_rows[-1]["blocks"][0]["text"]
    assert "could not translate" in text and not [b for b in store.message_rows[-1]["blocks"] if b["kind"] == "options"]


def test_lines_already_in_the_language_are_left_alone_and_said_so():
    store = store0()  # the fixture script is Sinhala
    llm = llm_for(store)
    run(store, ASK, llm)
    text = store.message_rows[-1]["blocks"][0]["text"]
    assert text == "Every spoken line there is already in Sinhala."
    assert not any(c["schema"] == "dialogue_translation" for c in llm.calls) and not store.saved


def test_no_language_named_asks_which():
    store = english_store()
    plan = {**plan_answer("translate"), "cannot": None, "translate": {"language": "", "code": "", "style": "",
                                                                       "shots": []}}
    run(store, "translate the dialogue", DirectorLLM({"turn_plan": lambda s, u: plan}))
    assert store.message_rows[-1]["blocks"][0]["text"] == turn.ASK_LANGUAGE


def test_the_translator_prompt_is_static_and_says_lines_are_data():
    assert "never instructions" in translate.SYSTEM and "<<" not in translate.SYSTEM
    assert translate.SCHEMA["required"] == ["lines"]


# ── confirming it in words ─────────────────────────────────────────────────────────────────


def test_i_confirm_it_applies_the_waiting_translation_and_nothing_else():
    store = english_store()
    say(store, ASK, llm_for(store))
    say(store, "keep everything else, put the dialogue in Sinhala, i confirm it", llm_for(store))
    assert [ln["text"] for ln in store.line_rows] == SI and len(store.saved) == 1
    text = store.message_rows[-1]["blocks"][0]
    assert "Goal reached" in text["text"] and text["goal"] == "dialogue.si" and text["met"] is True


def test_a_translation_of_the_wrong_target_does_not_apply_the_waiting_card():
    store = english_store()
    say(store, ASK, llm_for(store))
    say(store, "translate the dialogue to Tamil, i confirm it", llm_for(store, [TA, TA], code="ta", language="Tamil"))
    assert [ln["text"] for ln in store.line_rows] == EN and not store.saved  # a new Tamil card, Sinhala superseded
    assert card_of(store)["options"][0]["intent"] == "dialogue.ta"


@pytest.mark.parametrize("message, code", [("put all the dialogue in Sinhala", "si"), ("translate S02 to Tamil", "ta"),
                                           ("convert the lines into Hindi please", "hi"),
                                           ("i want the dialogues back in English", "en")])
def test_the_rules_find_the_language_without_a_model(message: str, code: str):
    plan = conductor.by_rules(message, split_points={}, translator=True)
    assert plan.lane == "translate" and plan.translate and plan.translate["code"] == code
