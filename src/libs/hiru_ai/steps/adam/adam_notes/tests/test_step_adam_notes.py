"""adam_notes: the critics' notes merged for the reviser, and the code's findings as text (plan/2026-11-04b §5.4)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hiru_ai.steps.adam.adam_notes import step

HERE = Path(__file__).resolve().parents[1]


def note(card: int, severity: str, text: str, kind: str = "change", cell: str = "") -> dict[str, Any]:
    return {"card": card, "severity": severity, "kind": kind, "cell": cell, "note": text}


def answer(lens: str, score: int, *notes: dict[str, Any]) -> dict[str, Any]:
    return {"lens": lens, "score": score, "notes": list(notes)}


def test_the_example_runs_alone():
    out = step.run(json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8")))
    assert out["notes"] == ["n1 [audience, medium, add -> other:2:dasun] card 2: Dasun's face is never in frame when "
                            "the call turns."]
    assert out["scores"] == {"audience": 3} and out["failed"] == 1


def test_notes_are_most_severe_first_and_a_lens_keeps_its_own_order_within_a_severity():
    out = step.run({"results": [
        answer("audience", 3, note(1, "low", "a"), note(2, "high", "b")),
        answer("editor", 4, note(3, "high", "c"), note(4, "medium", "d"))]})
    assert [n["note"] for n in out["kept"]] == ["b", "c", "d", "a"]
    assert out["notes"][0] == "n1 [audience, high, change] card 2: b"
    assert [n["id"] for n in out["kept"]] == ["n1", "n2", "n3", "n4"]  # the reviser answers a note by its id


def test_a_repeated_note_on_a_card_is_kept_once_and_a_note_about_the_scene_says_so():
    out = step.run({"results": [
        answer("audience", 3, note(2, "high", "The turn is not seen on her face.")),
        answer("opportunity", 3, note(2, "high", "the turn is not seen on her face, add a CU"), note(0, "low", "x"))]})
    assert len(out["kept"]) == 2 and out["notes"][-1] == "n2 [opportunity, low, change] the scene: x"


def test_the_list_is_capped_and_says_how_many_were_left_out():
    many = [answer(f"l{n}", 3, *[note(n, "medium", f"note {n} {k}") for k in range(4)]) for n in range(1, 5)]
    out = step.run({"results": many})
    assert len(out["notes"]) == 8 and out["dropped"] == 8


def test_an_add_note_names_the_cell_it_would_fill():
    out = step.run({"results": [answer("audience", 3, note(2, "high", "Dasun is not seen", "add", "other:2:dasun"))]})
    assert out["notes"] == ["n1 [audience, high, add -> other:2:dasun] card 2: Dasun is not seen"]
    assert out["kept"][0]["cell"] == "other:2:dasun" and out["kept"][0]["kind"] == "add"


def test_a_critic_that_failed_is_counted_and_the_rest_still_speak():
    out = step.run({"results": [None, answer("editor", 5)]})
    assert out == {"notes": [], "scores": {"editor": 5}, "failed": 1, "kept": [], "dropped": 0}


def test_the_scores_are_kept_apart_from_the_notes():
    out = step.run({"results": [answer("fidelity", 2, note(1, "high", "x"))]})
    assert out["scores"] == {"fidelity": 2} and "2" not in out["notes"][0]


def test_the_report_says_what_code_found_and_how_many_problems_are_open():
    out = step.run({
        "fidelity": {"breaks": [{"code": "new_person", "where": "moment m4", "reason": "a waiter appears"}]},
        "fit": {"runtime_s": 52, "cards": [{}, {}], "issues": [
            {"code": "line_overrun", "level": "overrun", "message": "line L2 runs 0.8 s past the take", "card": 3},
            {"code": "envelope", "level": "warning", "message": "12 s over", "card": None}]},
        "continuity": {"issues": [{"code": "axis_cross", "where": "card 5", "message": "crosses the line"}]},
        "feasibility": {"flags": [
            {"card": 2, "code": "screen_text", "risk": "high", "why": "text on a phone", "fix": "show a reaction",
             "addressed": False},
            {"card": 4, "code": "mirror", "risk": "high", "why": "a mirror", "fix": "avoid", "addressed": True}]},
        "score": {"percent": 82.5, "max": 12, "signals": [{"signal": "sound", "applicable": True, "checks": [
            {"card": None, "ok": False, "why": "no change of sound at the turn"}]}]}})
    assert out["problems"] == 4
    text = out["text"]
    assert "1 break(s)" in text and "[new_person] moment m4: a waiter appears" in text
    assert "52 s in 2 takes; 1 overrun(s)" in text and "[envelope] card -: 12 s over" in text
    assert "[axis_cross] card 5: crosses the line" in text
    assert "[screen_text] card 2 (high)" in text and "mirror" not in text
    assert "Craft score: 82.5%" in text and "sound: card -: no change of sound at the turn" in text


def test_a_clean_report_says_so():
    out = step.run({"fidelity": {}, "fit": {"runtime_s": 20, "cards": [{}], "issues": []}, "continuity": {},
                    "feasibility": {}})
    assert out["problems"] == 0 and "nothing invented" in out["text"] and "no overruns" in out["text"]
