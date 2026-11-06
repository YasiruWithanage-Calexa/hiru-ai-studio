"""Tests that live with the david_repair agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hiru_ai.agents.david.david_repair import agent
from hiru_ai.agents.david.david_repair.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES: list[dict[str, Any]] = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def test_the_prompt_is_static_text():
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert text.strip() and len(text.split()) <= 2500


def test_the_user_message_shows_the_involved_shots_in_full_and_the_rest_in_a_line():
    case = CASES[0]
    inp = Input.model_validate(case["input"])
    text = agent.user_message(inp)
    assert "<problems>" in text and "Line L1" in text and "<shots>" in text and "<script>" in text
    assert "<tried>" not in text and "<note>" not in text
    noted = agent.user_message(inp.model_copy(update={"note": "Closer.", "tried": ["round 1 changed: x"]}))
    assert "<note>\nCloser.\n</note>" in noted and "round 1 changed: x" in noted


def test_a_patch_is_a_list_of_replacements_and_an_empty_one_is_valid():
    empty = next(c for c in CASES if c["name"].startswith("nothing"))
    out = agent.finish(Input.model_validate(empty["input"]), Output.model_validate(empty["reply"]))
    assert out.replaces == [] and out.staging == [] and out.end_state == []


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
    shot = schema["properties"]["replaces"]["items"]["properties"]["shots"]["items"]["properties"]
    assert "cinematography" in shot["ir"]["properties"] and "$ref" not in str(schema)
    assert _open_objects(schema) == []


def test_the_manifest_uses_the_repair_tier():
    from hiru_ai.core import agents

    assert agents.build("david_repair").manifest.model == "repair"
