"""The Scene 2 thread of 2026-11-01 (plan/2026-11-01c): seven requests for Sinhala dialogue, answered with
invented promises and a false "already applied". The case is `sinhala-switch-loop` in
tests/eval/director_replay.json, played with the model answers recorded from that thread.

Phase 0 pinned the case as FAILING (it reproduced the thread: see plan/2026-11-01c/IMPLEMENTED.md). Phases 1 and 2
made every answer honest; since Phase 4 the translator does what was asked: the first request stages a card with
every line before and after, "i confirm it" applies it, and the lines are Sinhala with the English kept as source.
"""
from __future__ import annotations

import json
from typing import Any

from tests.services.director_chat.test_replay import ROOT, harness

ENGLISH = ["Mother, I am back.", "Sit down and eat."]


def play() -> tuple[Any, list[dict[str, Any] | None], list[tuple[int, list[str]]]]:
    """The thread turn by turn → (store, each turn's result or None for a click, (saves, line texts) after each)."""
    h = harness()
    case = next(c for c in json.loads((ROOT / "tests" / "eval" / "director_replay.json").read_text(encoding="utf-8"))
                ["cases"] if c["id"] == "sinhala-switch-loop")
    store = h.fixture_store(case)
    results: list[dict[str, Any] | None] = []
    states: list[tuple[int, list[str]]] = []
    for t in case["turns"]:
        if "choose" in t:
            h.choose(store, t["choose"]["block"], t["choose"]["option"])
            results.append(None)
        else:
            results.append(h.run_turn(store, h.RecordedModel(t["model"], store), t["person"]))
        states.append((store.saved, [str(ln["text"]) for ln in store.line_rows]))
    return store, results, states


def test_the_thread_now_passes_every_turn():
    report = harness().replay("rules", only="sinhala-switch-loop")
    (case,) = report["cases"]
    assert case["ok"], case["failures"]


def test_the_first_request_stages_a_card_and_saves_nothing():
    _, results, states = play()
    first = results[0]
    assert first and first["card"] and not first["ops"] and "not changed the script yet" in first["reply"]
    assert states[0] == (0, ENGLISH)  # nothing is saved until a person applies it
    (card,) = [b for b in first["blocks"] if b["kind"] == "options"]
    apply_option = card["options"][0]
    assert apply_option["intent"] == "dialogue.si" and apply_option["label"] == "Translate 2 spoken lines to Sinhala"
    assert [(row["was"], row["speaker"]) for row in apply_option["lines"]] == [(ENGLISH[0], "Nimal"),
                                                                              (ENGLISH[1], "Kamala")]
    assert all(harness().script_of(row["now"]) == "si" for row in apply_option["lines"])


def test_i_confirm_it_applies_it_and_the_english_is_kept_as_the_source():
    store, results, states = play()
    second = results[1]
    assert second and second["outcome"] == "applied" and "Goal reached" in second["reply"]
    saves, texts = states[1]
    assert saves == 1 and all(harness().script_of(t) == "si" for t in texts)
    assert [ln["source_text"] for ln in store.line_rows] == ENGLISH
    assert {ln["source_lang"] for ln in store.line_rows} == {"en"}


def test_nothing_is_changed_or_promised_after_that():
    _, results, states = play()
    for n in (2, 4, 5, 6):  # "do it", "do it right now", "no still ... english", "apply it"
        assert results[n] and not results[n]["ops"] and not results[n]["card"]
        assert states[n] == states[1]
    assert "nothing waiting" in str(results[2]["reply"]) and "already in Sinhala" in str(results[5]["reply"])


def test_the_oracles_read_a_script_apart():
    h = harness()
    assert h.script_of("අම්මේ, මම ආපහු ආවා.") == "si"
    assert h.script_of("Mother, I am back.") == "en"
    assert h.script_of("Mother, මම ආවා") == "mixed"
    assert h.script_of("...") == "none"
    assert h.PROMISE.search("If you want Sinhala, confirm and we'll switch everything.")
    assert h.PROMISE.search("Say the word and I'll apply it.")
    assert not h.PROMISE.search("The scene runs 44 s in 4 shots.")
    assert h.CLAIM.search("Your earlier Sinhala switch is already applied.")
    assert not h.CLAIM.search("Nothing is waiting to apply.")
    assert h.NEGATED.search("No, nothing has been applied.") and not h.NEGATED.search("It has been applied.")
