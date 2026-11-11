"""The product is the lab (plan/2026-11-08e phase 2-3): while `lab/raphael` exists, what the model is given is the
lab's. The
prompts are the lab's to the letter (stage 2's plus the variety lines, D-V), and the JSON schemas the tools are held
to are the
lab's. Deleting the lab skips this file."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from contracts.raphael.wire import SCHEMA_EDIT, SCHEMA_EXTRAS, SCHEMA_PUT, EditPlanW, ExtrasW, PutW
from hiru_ai.agents.raphael import wire_schema

REPO = Path(__file__).resolve().parents[2]
LAB = REPO / "lab"
AGENTS = REPO / "src" / "libs" / "hiru_ai" / "agents" / "raphael"

pytestmark = pytest.mark.skipif(not (LAB / "raphael").exists(), reason="the lab is gone")


def lab_text(name: str) -> str:
    return (LAB / "raphael" / "prompts" / f"{name}.md").read_text(encoding="utf-8").rstrip()


def product_text(agent: str) -> str:
    return (AGENTS / agent / "prompts" / "system.md").read_text(encoding="utf-8").rstrip()


ADDED_2026_11_08F = (
    "- FLOOR (plan/2026-11-08f).",
    "- COVERAGE (plan/2026-11-08f).",
    "- LONG ACTIONS (plan/2026-11-08f).",
    "- STATE (plan/2026-11-09).",
    "- SUMMARY (plan/2026-11-11).",  # each clip's `summary`: the shot told as one person explains it to another
    *("- BREAKDOWN (plan/2026-11-10).",) * 3,  # the director's breakdown: three lines
    "- PHONE (plan/2026-11-10).",  # a name on a phone screen is welcome; phone close-ups are must clips
    *("- PACKET (plan/2026-11-11).",) * 5,  # the scene packet as the first message (contracts.raphael.packet)
    "- SAFE DEPICTION (plan/2026-11-10b).",  # death and violence shown, never named (contracts.safe_depiction)
)


def test_stage_1_prompt_is_the_labs_must_only_prompt_plus_the_length_lines_and_nothing_else():
    """plan/2026-11-08f added three lines (the 80 % floor, coverage from the script's own time, long actions over
    consecutive clips) and plan/2026-11-09 one (the state ledger); every other line is the lab's, in the lab's order."""
    lab, product = lab_text("raphael_must"), product_text("raphael_planner")
    added = [line for line in product.splitlines() if line not in lab.splitlines()]
    assert [a.split(")", 1)[0] + ")." for a in added] == list(ADDED_2026_11_08F)
    assert [line for line in product.splitlines() if line not in added] == lab.splitlines()


def test_stage_2_prompt_is_the_labs_plus_the_variety_lines_and_nothing_else():
    lab, product = lab_text("cinematic"), product_text("raphael_cinematic")
    added = [line for line in product.splitlines() if line not in lab.splitlines()]
    assert len(added) == 6 and added[0].startswith("- VARIETY (D-V).")
    assert added[1].startswith("- STATE (plan/2026-11-09).")
    assert added[2].startswith("- SUMMARY (plan/2026-11-11).")  # each clip's `summary`
    assert added[3].startswith("- BREAKDOWN (plan/2026-11-10).")  # one line: the breakdown's shots are in the bin
    assert added[4].startswith("- PHONE (plan/2026-11-10).")  # the name on a phone screen
    assert added[5].startswith("- SAFE DEPICTION (plan/2026-11-10b).")  # contracts.safe_depiction
    assert [line for line in product.splitlines() if line not in added] == lab.splitlines()


@pytest.fixture(scope="module")
def lab_schema():
    sys.path[:0] = [str(LAB), str(REPO / "src"), str(REPO / "src" / "libs")]
    try:
        from raphael import schema  # the lab's, not the product's group

        return schema
    finally:
        sys.path[:3] = []


def with_summary(schema):
    """The lab's schema plus the one field added on 2026-11-11: every clip's `summary`, a required string written
    after `editor_note` (the only departure from the lab's clip; `contracts.raphael.wire.MenuW`)."""
    if isinstance(schema, dict):
        out = {k: with_summary(v) for k, v in schema.items()}
        props = out.get("properties")
        if isinstance(props, dict) and "editor_note" in props and "summary" not in props:
            keys = list(props)
            at = keys.index("editor_note") + 1
            summary = {"summary": {"title": "Summary", "type": "string"}}
            out["properties"] = {k: props[k] for k in keys[:at]} | summary | {k: props[k] for k in keys[at:]}
            req = list(out.get("required") or [])
            if "editor_note" in req:
                req.insert(req.index("editor_note") + 1, "summary")
            out["required"] = req
        return out
    if isinstance(schema, list):
        return [with_summary(v) for v in schema]
    return schema


def test_the_schemas_the_tools_are_held_to_are_the_labs(lab_schema):
    """The same fields, order, types and closed lists. A class docstring is not part of it: the lab's schema carried
    one on
    the cinematic clip alone, and the product sends none (the prompt says it)."""
    plain = wire_schema._plain

    assert wire_schema.design_schema(EditPlanW, SCHEMA_EDIT) == plain(lab_schema.edit_schema())
    assert wire_schema.design_schema(PutW, SCHEMA_PUT) == with_summary(plain(lab_schema.put_schema()))
    assert wire_schema.design_schema(ExtrasW, SCHEMA_EXTRAS) == with_summary(plain(lab_schema.extras_schema()))


def test_the_tools_are_the_labs_by_name_and_by_description():
    sys.path[:0] = [str(LAB), str(REPO / "src"), str(REPO / "src" / "libs")]
    try:
        from raphael import agent as lab_agent
    finally:
        sys.path[:3] = []
    lab = {t["name"]: t for t in lab_agent.tool_specs()}
    mine = {t["function"]["name"]: t["function"] for t in wire_schema.stage1_specs()}
    assert list(lab) == list(mine)
    for name, spec in lab.items():
        assert mine[name]["description"] == spec["description"]
        assert mine[name]["parameters"] == with_summary(spec["parameters"])
        assert mine[name]["strict"] is True
