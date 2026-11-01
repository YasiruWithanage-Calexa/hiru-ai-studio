"""The staging eval (scripts/eval_staging.py) in rules mode: offline, so CI holds the floor."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def load():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("eval_staging", ROOT / "scripts" / "eval_staging.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rules_mode_holds_the_floor_and_marked_voices_never_show():
    ev = load()
    scores, results = ev.evaluate(ev.NoModel())
    assert ev.failures(scores, "rules") == [], scores
    marked = {"phone_call_marked", "voice_from_kitchen", "radio_news", "tv_voice", "narrator", "flashback_voice",
              "intercom", "letter_read_aloud", "call_both_sides", "call_breaks_a_moment",
              "caller_named_in_prose"}
    for r in results:
        if r["id"] in marked:
            for h in r["heard"]:
                assert all(h not in s["on_screen"] and h not in s["refs"] for s in r["shots"]), r["id"]


HARD = {"call_breaks_a_moment", "drop_pickup_run", "exit_watched", "caller_named_in_prose", "closing_thought"}


def test_the_picture_metrics_hold_their_ceilings_on_the_hard_scenes():
    ev = load()
    scores, results = ev.evaluate(ev.NoModel())
    assert HARD <= {r["id"] for r in results}
    assert scores["crowded_shots"] == 0 and scores["voice_before_source"] == 0 and scores["inner_filmed"] == 0
    assert scores["info_carried"] >= 0.8
    assert ev.failures({**scores, "crowded_shots": 2}, "rules") == ["crowded_shots: 2 > 0"]
    assert ev.failures({**scores, "inner_filmed": 1, "voice_before_source": 1}, "model") == [
        "voice_before_source: 1 > 0", "inner_filmed: 1 > 0"]


def test_the_call_that_breaks_a_moment_is_shown_in_order():
    ev = load()
    _, results = ev.evaluate(ev.NoModel())
    case = next(r for r in results if r["id"] == "call_breaks_a_moment")
    sizes = [s["framing"] for s in case["shots"]]
    assert len(sizes) >= 7 and "WIDE" in sizes and len(set(sizes)) >= 3
    voice = next(s for s in case["shots"] if s["sound"] == "voiceover")
    anudi = next(i for i, n in case["names"].items() if n == "Anudi")
    assert voice["on_screen"] == [anudi]  # the voice is framed on the person who holds the phone
    assert "answers the phone" in " ".join(s["intent"] for s in case["shots"])
    assert "no idea" not in " ".join(s["intent"] for s in case["shots"])  # a thought is never filmed
