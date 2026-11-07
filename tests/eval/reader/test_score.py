"""The reader's accuracy scores (plan/2026-11-06f §5) on the Ekama gold: perfect against itself, and each fault costs
the score it should."""
from __future__ import annotations

import json
from pathlib import Path

from tests.eval.reader import score

from contracts.doc_read import Reading, to_parsed

GOLD = json.loads((Path(__file__).resolve().parent / "gold" / "ekama-sakshiya.json").read_text(encoding="utf-8"))


def parsed(episodes: list) -> object:
    return to_parsed(Reading(episodes=episodes))


def test_the_gold_scores_one_against_itself():
    names, aliases = score.gold_names(GOLD["answer"])
    got = score.score(parsed(GOLD["answer"]["episodes"]), parsed(GOLD["answer"]["episodes"]), aliases=aliases,
                      gold_canon=names, got_canon=names)
    assert got == dict.fromkeys(score.SCORES, 1.0)


def test_a_reworded_line_a_wrong_speaker_and_a_lost_time_each_cost():
    names, aliases = score.gold_names(GOLD["answer"])
    episodes = json.loads(json.dumps(GOLD["answer"]["episodes"]))
    scene = episodes[0]["scenes"][3]
    scene["blocks"][1]["text"] = "Driver kenek thamai."  # reworded
    scene["blocks"][2]["speaker"] = "Dinu"  # Suren's line given to Dinu... (block 2 is Dinu's: swap with block 1)
    scene["blocks"][1]["speaker"] = "Mudalali"
    episodes[0]["scenes"][0]["time_of_day"] = ""
    got = score.score(parsed(GOLD["answer"]["episodes"]), parsed(episodes), aliases=aliases, gold_canon=names,
                      got_canon=names[:-2])
    assert got["dialogue"] < 1 and got["words"] < 1 and got["time_of_day"] == 8 / 9 and got["canon"] < 1
    assert "| arm |" in score.table({"x": got})
