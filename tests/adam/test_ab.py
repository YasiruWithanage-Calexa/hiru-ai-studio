"""Phase 10 (plan/2026-11-04b): the tools that count a person's blind A/B and tune the score weights to their picks.

They count what people judged and decide nothing; the live runner refuses to spend model calls without being told to."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import adam_ab as ab
import adam_live as live


def record(a: str, b: str, pick: str, felt_a: int = 4, felt_b: int = 3, mute: int = 4) -> dict[str, Any]:
    return {"key": {"A": a, "B": b}, "proud_of": pick,
            "scores": {"A": {"felt_there": felt_a, "mute_test": mute}, "B": {"felt_there": felt_b, "mute_test": mute}}}


def test_the_targets_are_counted_from_the_records_that_have_a_key_and_a_choice():
    rows = [record("classic", "adam", "B"), record("adam", "classic", "A"), record("adam", "classic", "B"),
            record("adam", "classic", "A"), record("classic", "adam", "B"),  # adam preferred 4 of 5
            record("master", "adam", "neither", felt_a=5, felt_b=4),  # worse than the master
            record("adam", "master", "A"),  # preferred over the master
            {"key": {"A": "", "B": ""}, "proud_of": "A", "scores": {}}]  # not keyed yet: open
    out = ab.summarise(rows)
    assert out["records"] == 8 and out["open"] == 1
    t = out["targets"]
    assert t["adam_preferred_over_classic"] == {"value": 0.8, "target": 0.8, "judged": 5, "met": True}
    assert t["as_good_as_master"]["value"] == 0.5 and t["as_good_as_master"]["met"] is True
    assert t["felt_there_average"]["judged"] == 7


def test_no_data_is_no_data_not_a_pass():
    out = ab.summarise([])
    assert all(row["met"] is None and row["judged"] == 0 for row in out["targets"].values())


def test_adam_below_the_target_is_reported_as_not_met():
    out = ab.summarise([record("adam", "classic", "B"), record("classic", "adam", "A")])
    assert out["targets"]["adam_preferred_over_classic"]["met"] is False


def test_the_weights_move_toward_what_a_person_picks_and_a_signal_nobody_relies_on_stays_at_one():
    pairs = [{"a": {"sound": 1.0, "variety": 0.0, "ending": 1.0}, "b": {"sound": 0.0, "variety": 1.0, "ending": 1.0},
              "pick": "a"} for _ in range(3)]
    weights = ab.tune(pairs)
    assert weights["sound"] > 1.0 and weights["ending"] == 1.0
    equal_agree = sum(sum(p["a"].values()) > sum(p["b"].values()) for p in pairs)  # a tie: no agreement
    tuned_agree = sum(sum(weights[s] * v for s, v in p["a"].items()) > sum(weights[s] * v for s, v in p["b"].items())
                      for p in pairs)
    assert tuned_agree > equal_agree


def test_a_tie_is_not_counted_as_agreement():
    assert ab.tune([{"a": {"x": 1.0}, "b": {"x": 1.0}, "pick": "a"}]) == {"x": 1.0}


def test_the_summary_prints_and_a_missing_folder_is_not_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    assert ab.main(["--dir", str(tmp_path / "nope")]) == 0 and "no results yet" in capsys.readouterr().out
    (tmp_path / "x.json").write_text('{"key": {"A": "adam", "B": "classic"}, "proud_of": "A", "scores": {}}',
                                     encoding="utf-8")
    assert ab.main(["--dir", str(tmp_path)]) == 0
    assert "adam_preferred_over_classic" in capsys.readouterr().out


def test_the_live_runner_will_not_spend_model_calls_unless_told_to(capsys: pytest.CaptureFixture[str]):
    assert live.main([]) == 2
    assert "--yes" in capsys.readouterr().out
