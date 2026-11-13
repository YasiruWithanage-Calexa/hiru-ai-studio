"""Tests that live with the zora_author agent (ADR 0006)."""
from __future__ import annotations

from pathlib import Path

import yaml

from contracts.safe_depiction import PROMPT_LINE
from hiru_ai.agents.zora.zora_author import agent
from hiru_ai.agents.zora.zora_author.schema import Input, Output, TaskView
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]


def test_the_prompt_is_zoras_own_with_the_safe_depiction_line():
    mine = Prompt.load(HERE / "prompts" / "system.md").text
    assert mine.startswith("You are ZORA'S AUTHOR") and PROMPT_LINE.strip()[:60] in mine
    assert "{SAFE}" not in mine and "sound_mode: shot, value" in mine


def test_the_message_lays_out_each_task_and_the_faults_last():
    task = TaskView(instruction="make it tenser", writes=["camera", "timing"], on="S08, S09")
    text = agent.user_message(Input(scene="SCENE", tasks=[task], done=["S01 · size: MS → WIDE"],
                                    faults=["S11 overruns"]))
    assert text.startswith("CONVERSATION (recent):\n(none)\n\nSCENE\n\nALREADY DONE THIS TURN:\n"
                           "- S01 · size: MS → WIDE")
    assert "1. make it tenser\n   YOU MAY CHANGE: camera, timing\n   ON: S08, S09" in text
    assert text.endswith("(fix exactly these; change nothing else):\n- S11 overruns") and "VARIANTS" not in text


def test_the_wire_is_strict_and_the_cases_read_back():
    assert agent.output_schema()["title"] == "zora_author"
    cases = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))
    assert Output.model_validate(cases[1]["reply"]).variants[0].label == "Hold on Dinu"
    assert agent.memory_scope(Input(scene="", tasks=[], place="Garage", people=["Dinu"])) == {
        "place": "Garage", "people": ["Dinu"]}
