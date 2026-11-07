"""Tests that live with the zora_author agent (ADR 0006)."""
from __future__ import annotations

from pathlib import Path

import yaml

from hiru_ai.agents.zora.zora_author import agent
from hiru_ai.agents.zora.zora_author.schema import Input, Output, TaskView
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
PLANNER = HERE.parents[1] / "jonathan" / "jonathan_author" / "prompts" / "system.md"
LAB = HERE.parents[5] / "lab" / "zora" / "prompts" / "author.md"


def test_the_prompt_is_the_planners_to_the_letter_then_zoras_charter():
    mine = Prompt.load(HERE / "prompts" / "system.md").text
    assert mine.startswith(Prompt.load(PLANNER).text)
    assert "ZORA: YOU ARE NOW EDITING A PLAN YOU ALREADY MADE" in mine
    if LAB.exists():
        assert mine.endswith(Prompt.load(LAB).text)


def test_the_message_lays_out_each_task_and_the_faults_last():
    task = TaskView(instruction="make it colder", allowed=["treatment.approach", "shot.lens"], on="any shot",
                    must=["treatment.approach"])
    text = agent.user_message(Input(plan="PLAN", tasks=[task], done=["S03: lens 85mm"], faults=["S04 crosses"]))
    assert text.startswith("CONVERSATION (recent):\n(none)\n\nPLAN\n\nALREADY DONE THIS TURN:\n- S03: lens 85mm")
    assert "1. make it colder\n   YOU MAY WRITE ONLY: treatment.approach, shot.lens\n   ON: any shot\n" \
           "   MUST CHANGE: treatment.approach" in text
    assert text.endswith("(fix exactly these; change nothing else):\n- S04 crosses") and "VARIANTS" not in text


def test_the_wire_is_strict_and_the_cases_read_back():
    assert agent.output_schema()["title"] == "zora_author"
    cases = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))
    assert Output.model_validate(cases[1]["reply"]).variants[0].label == "Close first"
    assert agent.memory_scope(Input(plan="", tasks=[], place="Home", people=["Anudi"])) == {
        "place": "Home", "people": ["Anudi"]}
