"""Tests that live with the board_writer agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from contracts.board import (
    ONE_PANEL,
    Edit,
    Writer,
    board_prompt,
    colours_for,
    frame_sections,
    missing_panels,
    panel_answer,
    panel_prompt,
    writer_message,
)
from contracts.safe_depiction import PROMPT_LINE, blocking
from hiru_ai.agents.board_writer import agent
from hiru_ai.agents.board_writer.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def test_the_prompt_is_static_text_and_carries_safe_depiction():
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert text.strip()
    assert " ".join(PROMPT_LINE.split()).lstrip("- ") in " ".join(text.split())


def test_the_writer_is_told_never_to_describe_the_sheet_layout():
    """plan/2026-11-22 §3.3: code lays out the sheet; a grid in `world` contradicted each part's own grid."""
    text = " ".join(Prompt.load(HERE / "prompts" / "system.md").text.split())
    assert "Never describe the sheet's layout (grid, rows, columns, cells, panel count, gutters)" in text


def test_the_hooks_use_the_agents_own_types():
    inp = Input.model_validate({"message": "hello", "pictures": [{"b64": "iVBORw0KGgo="}]})
    assert agent.user_message(inp) == "hello"
    assert agent.images(inp) == [("image/png", "iVBORw0KGgo=")]


def test_the_eval_replies_are_valid_outputs():
    for case in CASES:
        if "reply" in case:
            Output.model_validate(case["reply"])


def test_a_recorded_answer_makes_a_clean_board_and_frame():
    """The recorded answer goes through the board prompt and a frame's sections with no blocked word and no colour
    left in the frame."""
    out = Writer.of(Output.model_validate(CASES[0]["reply"]).model_dump())
    colours = colours_for(["Nimal", "Aruni"])
    prompt = board_prompt(out, [1, 2], ["the location plate for Mahawewa canal"], colours)
    assert not blocking(prompt)
    assert "PANEL 2 (row 1, column 2)" in prompt and missing_panels(out, [1, 2]) == []
    frame = " ".join(frame_sections(out, 2, {"Aruni": "blue", "Nimal": "red"}, ["Nimal lies still."]))
    assert "Aruni stands at left" in frame and "the blue mannequin" not in frame.split("Background:")[-1]
    assert "eyes closed" in frame


def test_one_panel_mode_leaves_the_system_prompt_alone():
    """plan/2026-11-17 §3.2: the one-panel instructions travel at the END of the user message; the system prompt is
    the same, byte for byte, for a whole board and for one panel (one cached prompt)."""
    system = Prompt.load(HERE / "prompts" / "system.md").text
    assert "ONE PANEL" not in system
    board = Writer.of(CASES[0]["reply"])
    edit = Edit(kind="add", number=3, plan={"number": 3}, board=board, before=2)
    message = writer_message({}, colours_for(["Nimal"]), edit=edit)
    assert message.endswith(ONE_PANEL) and agent.user_message(Input(message=message)) == message
    case = next(c for c in CASES if c["name"] == "one panel added to an approved board")
    answer = panel_answer(Output.model_validate(case["reply"]).model_dump(), 4)
    assert answer is not None and answer.shot == 4 and "cream cup" in answer.picture
    prompt = panel_prompt(board, answer, ["the location plate for Colombo roadside"], {"Kasun": "red",
                                                                                    "office worker": "blue"})
    assert not blocking(prompt) and "THE PANEL" in prompt


def test_the_lab_answer_still_reads():
    """The lab's run_014 writer output (if the lab is still in the repo) is a valid Writer."""
    lab = Path(__file__).resolve().parents[6] / "lab" / "storyboard" / "runs" / "run_014" / "writer_output.json"
    if not lab.exists():
        return
    out = Writer.of(json.loads(lab.read_text(encoding="utf-8")))
    assert len(out.panels) == 9 and out.world and out.geography
