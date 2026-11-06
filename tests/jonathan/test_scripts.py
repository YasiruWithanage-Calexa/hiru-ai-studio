"""The live trial and the blind comparison (plan/2026-11-06b §7 phase 6, §8), offline.

The trial is a person's to start (it spends model calls), so these tests run it against a scripted model: that it
refuses without `--yes`, stops before its budget, runs the real planner with the stabiliser, saves each run and prices
it exactly. The comparison prints Jonathan's plan as full shot cards and names nobody."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.jonathan import gold
from tests.jonathan.test_system import plan_dump, route

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import jonathan_compare as compare
import jonathan_spike as spike

from hiru_ai.core import llm
from hiru_ai.core.testing import RoutedChatModel

PHONE = spike.EVAL / "scenes" / "phone_call.yaml"


@pytest.fixture(autouse=True)
def into_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spike, "SPIKE", tmp_path / "spike")
    monkeypatch.setattr(compare, "SPIKE", tmp_path / "spike")
    monkeypatch.setattr(compare, "COMPARE", tmp_path / "compare")
    monkeypatch.setattr(compare, "CHATGPT", tmp_path / "chatgpt")
    monkeypatch.setattr(compare, "ADAM_EVAL", tmp_path / "none")  # the other planners' saved runs are not on trial here


def per_tier(model: RoutedChatModel) -> Any:
    """Every tier answers as gpt-5, the model the trial prices (a scripted call reports a few tokens)."""
    return lambda tier: model.model_copy(update={"model_name": "gpt-5"})


def scripted(**routes: list[Any]) -> RoutedChatModel:
    return RoutedChatModel(routes={"jonathan_author": [], "jonathan_revise": [], **routes}, choose=route,
                           model_name="gpt-5")


# ── the trial ────────────────────────────────────────────────────────────────────────────────────


def test_it_refuses_to_start_without_yes_and_spends_nothing(capsys: pytest.CaptureFixture[str]):
    assert spike.main(["--repeat", "3"]) == 2
    out = capsys.readouterr().out
    assert "--yes" in out and "x 3 run(s)" in out


def test_the_default_scenes_never_include_the_one_the_prompt_shows():
    assert spike.EXAMPLE_SCENE not in spike.gold_names() and "phone_call" in spike.gold_names()


def test_a_gold_scene_is_given_to_the_planner_with_its_voice_only_speaker_present():
    name, scene, pack, craft = spike.load_scene(PHONE)
    assert name == "phone_call" and "Father" in scene.cast and scene.envelope_s is None
    assert [p["name"] for p in pack["production"]["people"]] == scene.cast and craft.story_objects == []


def test_a_scene_in_the_labs_shape_brings_its_people_style_guide_and_story_objects(tmp_path: Path):
    lab = {"id": "lab_scene", "heading": "EXT. ROAD - DAY", "style": "Monsoon drama.", "time": {"guide_s": 60},
           "story_objects": ["phone"], "people": [{"name": "Anudi", "code": "C02", "essence": "warm, curious"}],
           "scene": gold.raw()}
    path = tmp_path / "lab_scene.yaml"
    import yaml

    path.write_text(yaml.safe_dump(lab, allow_unicode=True), encoding="utf-8")
    name, scene, pack, craft = spike.load_scene(path)
    assert name == "lab_scene" and scene.envelope_s == 60 and craft.story_objects == ["phone"]
    assert pack["production"]["style_note"] == "Monsoon drama." and pack["production"]["people"][0]["essence"]


def test_a_run_goes_through_the_stabiliser_saves_the_plan_and_its_calls_and_prices_them():
    draft = plan_dump(gold.phone_call().without({13}))  # a craft gap: one revise pass
    model = scripted(jonathan_author=[draft], jonathan_revise=[plan_dump()])
    with llm.use_models(per_tier(model)):
        row = spike.run_one(PHONE, 1)
    assert row["revises"] == 1 and row["first"] == [0, 1] and row["score"] == [0, 0] and row["shots"] == 15
    saved = json.loads((spike.SPIKE / "phone_call" / "1.json").read_text(encoding="utf-8"))
    assert saved["planner"] == "jonathan" and saved["plan"]["treatment"]["logline"] and saved["measures"]
    usage = json.loads((spike.SPIKE / "phone_call" / "1.usage.json").read_text(encoding="utf-8"))
    assert len(usage) == row["calls"] == 2 and row["dollars"] == round(sum(spike.cost(r) for r in usage), 4)


def test_a_model_is_priced_by_its_exact_name_and_one_with_no_price_is_refused():
    assert spike.price_of("gpt-5") == (1.25, 0.125, 10.00) and spike.price_of("gpt-5-2025-08-07")[2] == 10.00
    assert spike.price_of("gpt-5.5")[2] == 30.00  # not billed as gpt-5 (the lab's prefix bug)
    assert spike.price_of("gpt-6.1-sol") == (2.00, 0.10, 10.00)  # Jonathan's model
    with pytest.raises(ValueError):
        spike.price_of("gpt-6")


def test_no_scene_starts_that_could_pass_the_budget(capsys: pytest.CaptureFixture[str],
                                                   monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("_common.load_env", lambda: None, raising=False)
    called: list[Any] = []
    monkeypatch.setattr(spike, "run_one", lambda path, n: called.append(n) or {})
    assert spike.main(["--yes", "--scene", "phone_call", "--budget", "0.50"]) == 1
    assert called == [] and "could pass the $0.50 budget" in capsys.readouterr().out


def test_the_summary_says_per_scene_whether_the_gates_points_hold():
    rows = [{"scene": "x", "run": n, "calls": c, "first": [1, 2], "score": s, "shots": 18, "take_s": 90, "use_s": 66,
             "guide_s": 60.0, "seconds": 200.0, "dollars": 0.25} for n, c, s in ((1, 2, [0, 0]), (2, 3, [0, 1]))]
    table = spike.summary(rows)
    assert "| x | 2 | yes | 2 of 2 |" in table and "Spent: $0.50." in table
    rows[1]["score"] = [1, 0]
    assert "| x | 2 | no | 1 of 2 |" in spike.summary(rows)


# ── the blind comparison ─────────────────────────────────────────────────────────────────────────


def test_jonathans_list_is_the_labs_shot_card_under_each_sequence():
    text = compare.from_jonathan({"plan": plan_dump()}, gold.raw())
    assert text.startswith("A. EASE: the world and the joke") and "B. THE CALL:" in text
    assert "SHOT 01 — extreme wide, 4 s (keeps 3 s)" in text and "Camera: eye level · 24mm: the place" in text
    assert "Purpose: The world:" in text and "Says: Dasun:" in text and "Audio: lake water" in text
    assert "(the picture stays on Anudi while the line is heard)" in text and "Visual 0-2s:" in text
    assert "take_s" not in text and "blocks" not in text


def test_the_page_shuffles_the_letters_names_nobody_and_keeps_the_key_apart():
    page, key = compare.blind_page("phone_call", {"jonathan": "1. wide", "chatgpt": "1. close", "classic": "1. medium",
                                                  "adam": "1. insert"}, seed=1)
    assert sorted(key) == ["A", "B", "C", "D"] and sorted(key.values()) == ["adam", "chatgpt", "classic", "jonathan"]
    for who in key.values():
        assert who not in page.lower().replace("chatgpt-", "")
    assert "Plan A" in page and "I can see the scene" in page and "it is filmable in Veo" in page
    _, again = compare.blind_page("phone_call", {"jonathan": "1. wide", "chatgpt": "1. close", "classic": "1. medium",
                                                 "adam": "1. insert"}, seed=1)
    assert again == key  # the same seed gives the same letters, so a page can be made again


def test_a_scene_with_one_contestant_makes_no_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    model = scripted(jonathan_author=[plan_dump()])
    with llm.use_models(per_tier(model)):
        spike.run_one(PHONE, 1)
    assert compare.main(["--scene", "phone_call"]) == 0
    assert "a comparison needs two or more" in capsys.readouterr().out
    assert not (tmp_path / "compare" / "phone_call" / "blind.html").exists()


def test_two_contestants_make_the_lists_the_page_and_the_key_from_the_latest_run(tmp_path: Path):
    model = scripted(jonathan_author=[plan_dump(), plan_dump()])
    with llm.use_models(per_tier(model)):
        spike.run_one(PHONE, 1)
        spike.run_one(PHONE, 2)
    (tmp_path / "chatgpt").mkdir()
    (tmp_path / "chatgpt" / "phone_call.txt").write_text("1. Wide of the bench.\n", encoding="utf-8")
    assert compare.saved_run("phone_call", None).name == "2.json"
    assert compare.main(["--scene", "phone_call"]) == 0
    folder = tmp_path / "compare" / "phone_call"
    assert sorted(p.name for p in folder.iterdir()) >= ["blind.html", "chatgpt.txt", "jonathan.txt", "key.json"]
    assert "ChatGPT" not in (folder / "blind.html").read_text(encoding="utf-8")
    assert sorted(json.loads((folder / "key.json").read_text(encoding="utf-8")).values())[:2] == ["chatgpt", "jonathan"]
