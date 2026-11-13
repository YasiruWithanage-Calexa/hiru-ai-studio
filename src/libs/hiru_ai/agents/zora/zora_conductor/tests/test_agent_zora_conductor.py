"""Tests that live with the zora_conductor agent (ADR 0006)."""
from __future__ import annotations

from pathlib import Path

import yaml

from hiru_ai.agents.zora.zora_conductor import agent
from hiru_ai.agents.zora.zora_conductor.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
LAB = HERE.parents[5] / "lab" / "zora_rows" / "prompts" / "conductor.md"


def test_the_prompt_is_the_labs_with_the_sound_mode_op():
    mine = Prompt.load(HERE / "prompts" / "system.md").text
    assert "- sound_mode: shot, value" in mine
    if LAB.exists():  # the lab stays as the evidence
        lab = Prompt.load(LAB).text
        assert mine.startswith(lab.split("- sound_mode")[0][:200])


def test_the_message_is_the_labs_and_a_retry_appends_what_was_wrong_last():
    inp = Input(scene="SCENE", message="Drop S08.", transcript=[f"m{i}" for i in range(6)], rejected=["a split"])
    first = agent.user_message(inp)
    assert first == ("CONVERSATION (recent):\nm2\nm3\nm4\nm5\n\nSCENE\n\nTHE PERSON REJECTED IN THIS THREAD (do not "
                     "offer again): a split\n\nLATEST MESSAGE FROM THE DIRECTOR:\nDrop S08.")
    again = agent.user_message(inp.model_copy(update={"problems": ["no ops and no tasks on lane edit"]}))
    assert again.startswith(first) and again.endswith("- no ops and no tasks on lane edit")


def test_the_wire_is_strict_and_the_answer_reads_back():
    schema = agent.output_schema()
    assert schema["title"] == "zora_conductor" and schema["additionalProperties"] is False
    assert "shape" not in schema["properties"]["lane"]["enum"] and "translate" not in schema["properties"]
    cases = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))
    out = Output.model_validate(cases[0]["reply"])
    assert out.lane == "edit" and out.ops[0]["value"] == "WIDE" and not out.does_nothing()
    assert Output(lane="craft").does_nothing() and not Output(lane="clarify").does_nothing()
