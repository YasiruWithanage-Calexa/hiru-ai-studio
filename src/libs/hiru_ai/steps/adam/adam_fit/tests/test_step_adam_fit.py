"""adam_fit: moments and cards on the Veo clock; overruns are reported, never trimmed (plan/2026-11-04b §5.3, §5.6)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hiru_ai.steps.adam.adam_fit import step

HERE = Path(__file__).resolve().parents[1]
FIVE = "one two three four five"  # 5 words: 2.27 s at 2.2 words a second
LONG = " ".join(["word"] * 14)  # 14 words: 6.4 s


def scene(text: str = FIVE, delivery: str = "", envelope: float | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"cast": ["A"], "blocks": [
        {"index": 0, "kind": "dialogue", "speaker": "A", "line_id": "L1", "text": text, "delivery": delivery}]}
    if envelope:
        out["envelope_s"] = envelope
    return out


def moment(seconds: float = 2.5, lines: tuple[str, ...] = ("L1",)) -> dict[str, Any]:
    return {"id": "m1", "tier": "script", "serves": ["b0"], "lines": list(lines), "seconds_need": seconds}


def card(take: int = 4, **extra: Any) -> dict[str, Any]:
    return {"number": 1, "moments": ["m1"], "size": "MCU", "take_s": take, **extra}


def run(sc: dict[str, Any], moments: list[dict[str, Any]], cards: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return step.run({"scene": sc, "moments": moments, "cards": cards, **extra})


def issue_codes(out: dict[str, Any]) -> list[str]:
    return [i["code"] for i in out["issues"]]


def test_the_example_runs_alone():
    out = step.run(json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8")))
    assert out["ok"] and out["runtime_s"] == 4


def test_a_line_that_fits_reports_its_clock():
    out = run(scene(), [moment()], [card(4)])
    assert out["ok"] and out["overruns"] == 0
    row = out["cards"][0]
    assert row["need_s"] == 3.5  # 2.5 s of picture, a half second lead-in, a half second tail
    assert row["lines"][0]["start_s"] == 0.5 and row["fits"] and row["suggest_take_s"] == 4


def test_a_line_that_runs_past_the_take_is_reported_and_never_trimmed():
    out = run(scene(LONG), [moment(3.0)], [card(4)])
    assert not out["ok"]
    assert "line_overrun" in issue_codes(out) and "word_budget" in issue_codes(out)
    assert out["cards"][0]["lines"][0]["overrun_s"] > 0
    assert out["cards"][0]["suggest_take_s"] == 8  # what would hold it; nothing was changed
    assert out["cards"][0]["words"] == 14


def test_a_slow_delivery_takes_longer():
    quick = run(scene(delivery=""), [moment(0.5)], [card(4)])["cards"][0]["need_s"]
    slow = run(scene(delivery="whispered, halting"), [moment(0.5)], [card(4)])["cards"][0]["need_s"]
    assert slow > quick


def test_a_card_that_asks_for_more_than_eight_seconds_is_crowded():
    out = run(scene(), [moment(9.0)], [card(8)])
    assert "crowded" in issue_codes(out) and not out["ok"]
    assert out["cards"][0]["suggest_take_s"] is None


def test_a_take_that_veo_cannot_make_is_reported():
    out = run(scene(), [moment()], [card(5)])
    assert "bad_length" in issue_codes(out) and not out["ok"]


def test_a_moment_with_zero_seconds_plays_under_the_one_beside_it():
    two = [moment(2.5), {"id": "m2", "tier": "elaboration", "kind": "baseline", "serves": ["b0"], "who": ["A"],
                         "seconds_need": 0}]
    out = run(scene(), two, [{**card(4), "moments": ["m2", "m1"]}])
    assert out["cards"][0]["need_s"] == 3.5


def test_use_s_longer_than_the_take_is_an_error_and_a_shorter_one_waits_for_the_final_cut():
    assert "use_over_take" in issue_codes(run(scene(), [moment()], [card(4, use_s=5)]))
    out = run(scene(), [moment()], [card(4, use_s=3)])
    assert "trim_not_ready" in issue_codes(out) and out["ok"]  # a warning, not an overrun
    assert "trim_not_ready" not in issue_codes(run(scene(), [moment()], [card(4, use_s=3)], editorial=True))
    assert "use_too_short" in issue_codes(run(scene(), [moment()], [card(4, use_s=1)], editorial=True))


def test_the_scene_is_never_squeezed_to_fit_its_envelope():
    out = run(scene(envelope=3), [moment()], [card(4)])
    assert out["over_envelope_s"] == 1 and "envelope" in issue_codes(out)
    assert out["ok"] and out["runtime_s"] == 4  # reported, not repaired


def two_people() -> dict[str, Any]:
    return {"cast": ["A", "B"], "blocks": [{"index": 0, "kind": "dialogue", "speaker": "A", "line_id": "L1",
                                            "text": FIVE}]}


def test_an_off_speaker_line_must_play_over_a_listener_who_is_not_the_speaker():
    """Plan 2026-11-04c F6: "I'll come" over her own hands is refused; over the person who hears it is fine."""
    over = lambda who: [card(4, lines=[{"line_id": "L1", "on_speaker": False, "over_whom": who}])]  # noqa: E731
    for who in ("A", "", "the phone"):  # the speaker's own face, no one, an object
        out = run(two_people(), [moment()], over(who))
        bad = [i for i in out["issues"] if i["code"] == "bad_listener"]
        assert len(bad) == 1 and bad[0]["level"] == "overrun" and bad[0]["card"] == 1 and not out["ok"]
    assert run(two_people(), [moment()], over("B"))["ok"]
    on_speaker = [card(4, lines=[{"line_id": "L1", "on_speaker": True}])]
    assert "bad_listener" not in issue_codes(run(two_people(), [moment()], on_speaker))


def test_with_trims_on_a_two_second_reaction_from_a_four_second_take_counts_two_seconds():
    reaction = card(4, beats=[{"window": [0, 2], "action": "he reads her face"}], use_s=2.0, lines=[])
    out = run(two_people(), [{**moment(), "lines": [], "seconds_need": 2.0}], [reaction], editorial=True)
    assert out["ok"] and out["runtime_s"] == 2.0 and out["cards"][0]["use_s"] == 2.0
    assert run(two_people(), [{**moment(), "lines": [], "seconds_need": 2.0}], [reaction])["runtime_s"] == 4


def test_a_malformed_plan_is_reported_not_raised():
    out = step.run({"scene": scene(), "moments": [{"id": "m1"}], "cards": []})
    assert not out["ok"] and out["issues"][0]["code"] == "malformed"
