"""Raphael's packet path in the system (plan/2026-11-11 phase 4): the stored packet becomes stage 1's opening, the line
ids
are the scene's real rows, and there is no director's breakdown on this path. No model, no database."""

from __future__ import annotations

import json
from pathlib import Path

from hiru_ai.core.context import RunContext
from hiru_ai.systems.raphael.raphael_shot_planner import scene as raphael

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "raphael"


def _packet(name: str) -> dict:
    return json.loads((FIX / f"packet_ekama_{name}.json").read_text(encoding="utf-8"))


def _lines(n: int) -> list[dict]:
    return [{"id": f"row-{i}", "ord": i} for i in reversed(range(n))]  # any order: matched by `ord`


def test_the_line_ids_are_the_scene_s_rows_in_order() -> None:
    p = _packet("s02")
    spoken = [b for b in p["E_blocks"] if b["kind"] == "dialogue" and b["speaker"]]
    made = raphael.from_packet(p, _lines(len(spoken)))
    assert made is not None
    opening, script, line_ids = made
    assert opening.startswith("<packet>") and script.blocks
    shorts = sorted(line_ids, key=lambda k: int(k[1:]))
    assert [line_ids[k] for k in shorts] == [f"row-{i}" for i in range(len(spoken))]
    assert all(script.blocks[int(k[1:])].line_id == k for k in shorts)


def test_a_scene_whose_lines_do_not_match_is_not_planned_from_the_packet() -> None:
    p = _packet("s08")
    spoken = [b for b in p["E_blocks"] if b["kind"] == "dialogue" and b["speaker"]]
    assert raphael.from_packet(p, _lines(len(spoken) + 1)) is None


def test_the_packet_opening_is_stage_one_s_message_and_needs_no_breakdown() -> None:
    p = _packet("s02")
    spoken = [b for b in p["E_blocks"] if b["kind"] == "dialogue" and b["speaker"]]
    opening, script, line_ids = raphael.from_packet(p, _lines(len(spoken)))  # type: ignore[misc]
    planner = raphael.Planner(
        RunContext(),
        script,
        number=2,
        line_ids=line_ids,
        production={},
        context={},
        opening=opening,
        use_breakdown=True,
    )
    assert planner.opening1() == opening and planner.use_breakdown is False
    other = raphael.Planner(
        RunContext(),
        script,
        number=2,
        line_ids=line_ids,
        production={},
        context={},
        opening=opening.replace("Plan this scene.", "Plan it."),
    )
    assert planner.input_hash() != other.input_hash()  # another packet is another input
