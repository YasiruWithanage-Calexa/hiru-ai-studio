"""Tests that live with the jonathan_revise agent (ADR 0006): deleting the folder deletes them. That its message is the
cinematic lab's `revise_message` to the letter is `tests/jonathan/test_lab_parity.py`."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hiru_ai.agents.jonathan.jonathan_revise import agent
from hiru_ai.agents.jonathan.jonathan_revise.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES: list[dict[str, Any]] = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def test_the_prompt_is_the_authors_to_the_letter():
    mine = Prompt.load(HERE / "prompts" / "system.md").text
    assert mine == Prompt.load(HERE.parent / "jonathan_author" / "prompts" / "system.md").text


def test_the_message_is_the_authors_then_its_draft_then_what_code_found_then_the_ask():
    inp = Input.model_validate(CASES[0]["input"])
    text = agent.user_message(inp)
    assert text.startswith(inp.pack + "\n\n<draft>\n{") and "\n</draft>\n\n<findings>\n" in text
    assert "Problems code found in the draft (fix every one):\n- Line L1 (Dasun" in text
    assert "Craft gaps (improve them where the scene allows it):\n- none" in text
    assert text.endswith(agent.ASK) and "A person's note" not in text


def test_a_craft_gap_is_listed_with_its_label_and_detail_and_a_note_comes_last():
    inp = Input.model_validate(CASES[1]["input"])
    text = agent.user_message(inp)
    assert "- none\n\nCraft gaps" in text and "reaction or listener shot" in text and "none for L8" in text
    noted = agent.user_message(inp.model_copy(update={"note": "Open  closer\non the two of them."}))
    assert "A person's note on the plan (do what it asks, within the rules that never bend):\n" \
           "- Open closer on the two of them.\n</findings>" in noted


def test_the_answer_is_the_whole_plan_cleaned_like_the_authors():
    case = CASES[0]
    reply = Output.model_validate(case["reply"])
    out = agent.finish(Input.model_validate(case["input"]), reply)
    assert out == reply and len(out.shots) == 15


def _open_objects(node: Any, path: str = "") -> list[str]:
    """Where a schema breaks OpenAI's strict mode: an object open to more keys, or with one left optional."""
    found: list[str] = []
    if isinstance(node, dict):
        props = node.get("properties")
        if node.get("type") == "object" and (node.get("additionalProperties") is not False
                                             or set(node.get("required", [])) != set(props or {})):
            found.append(path or "/")
        for k, v in node.items():
            found += _open_objects(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found += _open_objects(v, f"{path}/{i}")
    return found


def test_the_schema_the_model_is_held_to_is_strict_and_carries_the_clip_schema():
    schema = agent.output_schema()
    shot = schema["properties"]["shots"]["items"]["properties"]
    assert "cinematography" in shot["ir"]["properties"] and "$ref" not in str(schema)
    assert _open_objects(schema) == []


def test_the_manifest_uses_the_jonathan_tier():
    from hiru_ai.core import agents

    built = agents.build("jonathan_revise")
    assert built.manifest.model == "jonathan" and built.manifest.timeout_s == 900
