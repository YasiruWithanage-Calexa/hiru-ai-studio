"""Phase 2 and 6 tools (plan/2026-11-05e §9, §10): the spike and the blind comparison, offline.

The spike is a person's to start (it spends model calls), so these tests run it against a scripted model: that it
refuses
without `--yes`, writes what it says it writes, measures configuration A (JSON directly) and B (free text, then a small
model), prices the calls and writes David's plan beside a pasted ChatGPT answer. The comparison page names nobody."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.david import gold
from tests.david.test_system import EMPTY_PATCH, MARKS, per_tier, plan_dump

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import david_compare as compare
import david_spike as spike

from hiru_ai.core import llm
from hiru_ai.core.testing import RoutedChatModel


@pytest.fixture(autouse=True)
def into_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spike, "SPIKE", tmp_path / "spike")
    monkeypatch.setattr(compare, "SPIKE", tmp_path / "spike")
    monkeypatch.setattr(compare, "COMPARE", tmp_path / "compare")
    monkeypatch.setattr(compare, "CHATGPT", tmp_path / "chatgpt")
    monkeypatch.setattr(compare, "ADAM_EVAL", tmp_path / "none")  # the other planners' saved runs are not on trial here


def route(messages: list[Any]) -> str:
    system = str(messages[0].content)
    if "another writer will put it in the exact format" in system:
        return "free"
    if "Put the plan you are given into the format" in system:
        return "format"
    return next(k for k, mark in MARKS.items() if mark in system)


def scripted(**routes: list[Any]) -> RoutedChatModel:
    return RoutedChatModel(routes={"david_author": [], "david_repair": [], "free": [], "format": [], **routes},
                           choose=route, model_name="gpt-5")


# ── the spike ────────────────────────────────────────────────────────────────────────────────


def test_it_refuses_to_start_without_yes_and_spends_nothing(capsys: pytest.CaptureFixture[str]):
    assert spike.main([]) == 2
    assert "--yes" in capsys.readouterr().out


def test_the_default_scenes_never_include_the_one_the_prompt_shows():
    names = spike.default_scenes()
    assert "phone_call" in names and spike.EXAMPLE_SCENE not in names and len(names) == 4


def test_configuration_a_asks_the_author_once_saves_the_plan_and_its_calls_and_prices_them(tmp_path: Path):
    model = scripted(david_author=[plan_dump()])
    with llm.use_models(per_tier(model)):
        row = spike.run_one("A", "phone_call", None)
    assert row["calls"] == 1 and row["repairs"] == 0 and row["shots"] == 10 and row["left"] == {
        "repair": 0, "drop": 0, "report": 0}
    assert row["input"] == 100 and row["output"] == 20 and row["dollars"] > 0
    saved = json.loads((tmp_path / "spike" / "A" / "phone_call.json").read_text(encoding="utf-8"))
    assert saved["planner"] == "david" and len(saved["plan"]["shots"]) == 10
    assert json.loads((tmp_path / "spike" / "A" / "phone_call.usage.json").read_text(encoding="utf-8"))


def test_the_first_pass_counts_what_code_found_in_the_authors_own_answer_before_any_repair():
    plan = plan_dump()
    plan["shots"][1]["lines"] = []  # the author forgot Dasun's line
    model = scripted(david_author=[plan], david_repair=[EMPTY_PATCH])
    with llm.use_models(per_tier(model)):
        row = spike.run_one("A", "phone_call", None)
    assert row["first"]["repair"] >= 1 and row["repairs"] == 1 and row["left"]["repair"] >= 1
    assert row["calls"] == 2


def test_configuration_b_writes_free_text_then_a_small_model_puts_it_in_the_format():
    model = scripted(free=[json.dumps(plan_dump())], format=[plan_dump()])
    with llm.use_models(per_tier(model)):
        row = spike.run_one("B", "phone_call", None)
    assert [route(c) for c in model.calls] == ["free", "format"] and row["shots"] == 10 and row["repairs"] == 0
    # (a scripted model reports no usage through the callbacks a live call carries, so the tokens are not asserted here)


def test_a_model_not_listed_is_priced_as_the_nearest_listed_one_and_a_small_one_costs_less():
    big = spike.cost({"model": "gpt-5", "input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 1000})
    small = spike.cost({"model": "gpt-5-mini", "input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 1000})
    assert big == pytest.approx(0.01125) and small < big
    assert spike.cost({"model": "gpt-9", "input_tokens": 1000, "output_tokens": 1000}) == big


def test_the_summary_table_has_a_row_per_configuration_and_nothing_made_up():
    rows = [{"config": "A", "scene": "x", "calls": 1, "repairs": 0, "shots": 9, "seconds": 120.0,
             "first": {"repair": 0, "mend": 2, "drop": 0, "report": 1}, "left": {"repair": 0, "drop": 0, "report": 1},
             "input": 1, "cached": 0, "output": 2, "reasoning": 1, "dollars": 0.2}]
    table = spike.summary(rows)
    assert "| A | 1 |" in table and "| B |" not in table and "| C |" not in table


def test_chatgpts_pasted_answer_is_written_beside_davids_plan_and_a_scene_without_one_is_skipped(tmp_path: Path):
    model = scripted(david_author=[plan_dump()])
    with llm.use_models(per_tier(model)):
        spike.run_one("A", "phone_call", None)
    (tmp_path / "chatgpt").mkdir()
    pasted = "1. Wide of the bench.\n2. Close on Anudi.\n"
    (tmp_path / "chatgpt" / "phone_call.txt").write_text(pasted, encoding="utf-8")
    written = spike.side_by_side(["phone_call", "arrival"], "A", None)
    assert [p.name for p in written] == ["phone_call.md"]
    text = written[0].read_text(encoding="utf-8")
    assert "Close on Anudi." in text and "Anudi" in text and "ඉතින් මම කිව්වා" in text  # the script's words for the line


# ── the blind comparison ─────────────────────────────────────────────────────────────────────────


def test_a_plain_list_has_size_take_picture_lines_and_sound_and_none_of_the_formats_jargon():
    scene = gold.raw()
    text = compare.from_david({"plan": plan_dump()}, scene)
    assert "1. wide, 4 s:" in text and "Says: Dasun:" in text and "Sound:" in text
    assert "(the picture stays on Anudi while the line is heard)" in text and "Silence." not in text
    assert "ir" not in text.split() and "take_s" not in text and "blocks" not in text


def test_the_page_shuffles_the_letters_names_nobody_and_keeps_the_key_apart():
    page, key = compare.blind_page("phone_call", {"david": "1. wide", "chatgpt": "1. close", "classic": "1. medium",
                                                  "adam": "1. insert"}, seed=1)
    assert sorted(key) == ["A", "B", "C", "D"] and sorted(key.values()) == ["adam", "chatgpt", "classic", "david"]
    for who in key.values():
        assert who not in page.lower().replace("chatgpt-", "")
    assert "Plan A" in page and "I can see the scene" in page and "it is filmable in Veo" in page
    _, again = compare.blind_page("phone_call", {"david": "1. wide", "chatgpt": "1. close", "classic": "1. medium",
                                                 "adam": "1. insert"}, seed=1)
    assert again == key  # the same seed gives the same letters, so a page can be made again


def test_a_scene_with_one_contestant_makes_no_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    model = scripted(david_author=[plan_dump()])
    with llm.use_models(per_tier(model)):
        spike.run_one("A", "phone_call", None)
    assert compare.main(["--scene", "phone_call", "--config", "A"]) == 0
    assert "a comparison needs two or more" in capsys.readouterr().out
    assert not (tmp_path / "compare" / "phone_call" / "blind.html").exists()


def test_two_contestants_make_the_lists_the_page_and_the_key(tmp_path: Path):
    model = scripted(david_author=[plan_dump()])
    with llm.use_models(per_tier(model)):
        spike.run_one("A", "phone_call", None)
    (tmp_path / "chatgpt").mkdir()
    (tmp_path / "chatgpt" / "phone_call.txt").write_text("1. Wide of the bench.\n", encoding="utf-8")
    assert compare.main(["--scene", "phone_call", "--config", "A"]) == 0
    folder = tmp_path / "compare" / "phone_call"
    assert sorted(p.name for p in folder.iterdir()) >= ["blind.html", "chatgpt.txt", "david.txt", "key.json"]
    assert "ChatGPT" not in (folder / "blind.html").read_text(encoding="utf-8")
    assert sorted(json.loads((folder / "key.json").read_text(encoding="utf-8")).values())[:2] == ["chatgpt", "david"]
