from __future__ import annotations

from tests.hiru_ai.steps_fixtures import run_ctx
from tests.services.director_chat.conftest import fixture_scene

from hiru_ai.tools.dialogue_read import tool


def test_lines_come_back_in_order_exactly_as_written_in_sinhala():
    scene, lines, shots = fixture_scene(3)
    out = tool.run(tool.Args(scene_id=scene["id"]), run_ctx(scene, lines, shots, canon=[]))
    assert [row["text"] for row in out.lines] == [ln["text"] for ln in lines]
    assert any("බෝට්ටුව" in row["text"] for row in out.lines)
    assert [row["ord"] for row in out.lines] == sorted(row["ord"] for row in out.lines)


def test_only_the_dialogue_columns_are_returned():
    scene, lines, shots = fixture_scene(0)
    out = tool.run(tool.Args(scene_id=scene["id"]), run_ctx(scene, lines, shots, canon=[]))
    assert set(out.lines[0]) <= set(tool.COLUMNS) and "production_id" not in out.lines[0]
