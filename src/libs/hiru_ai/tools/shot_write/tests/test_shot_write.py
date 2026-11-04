from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from tests.hiru_ai.steps_fixtures import felt_scene, run_ctx

from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ToolRefused
from hiru_ai.tools.shot_write import tool


def setup() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], RunContext]:
    scene, lines, shots = felt_scene()
    return scene, lines, shots, run_ctx(scene, lines, shots)


def test_a_fresh_plan_replaces_the_scenes_shots_and_rebinds_its_lines():
    scene, lines, shots, ctx = setup()
    new = [{**shots[0], "id": "n1", "number": 1}]
    rebound = [{**lines[0], "beat_index": 2}]
    out = tool.run(tool.Args(mode="plan", scene_id=scene["id"], shots=new, lines=rebound,
                             scene_fields={"status": "split"}), ctx)
    assert (out.shots, out.lines) == (1, 1)
    assert [s["id"] for s in ctx.ports.scenes.shot_rows] == ["n1"]  # type: ignore[union-attr]
    assert ctx.ports.scenes.lines(scene["id"])[0]["beat_index"] == 2  # type: ignore[union-attr]


def test_a_plan_never_rewords_adds_or_moves():
    scene, lines, shots, ctx = setup()
    with pytest.raises(ToolRefused, match="re-binds"):
        tool.run(tool.Args(mode="plan", scene_id=scene["id"], lines=[{**lines[0], "text": "better"}]), ctx)
    with pytest.raises(ToolRefused, match="re-binds"):
        tool.run(tool.Args(mode="plan", scene_id=scene["id"], lines=[{"id": "x", "text": "new"}]), ctx)
    with pytest.raises(ToolRefused, match="another scene"):
        tool.run(tool.Args(mode="plan", scene_id=scene["id"], shots=[{**shots[0], "scene_id": "elsewhere"}]), ctx)
    with pytest.raises(ToolRefused, match="production or episode"):
        tool.run(tool.Args(mode="plan", scene_id=scene["id"], scene_fields={"episode_id": "e"}), ctx)


def test_a_design_is_saved_on_a_shot_of_the_scene_only():
    scene, _, shots, ctx = setup()
    tool.run(tool.Args(mode="design", scene_id=scene["id"], shot_id=shots[0]["id"], ir={"a": 1}, design={"b": 2}), ctx)
    assert ctx.ports.scenes.designs[shots[0]["id"]] == {"ir": {"a": 1}, "design": {"b": 2}}  # type: ignore[union-attr]
    with pytest.raises(ToolRefused, match="not in this scene"):
        tool.run(tool.Args(mode="design", scene_id=scene["id"], shot_id="other", ir={}, design={}), ctx)


def test_a_prompt_version_is_added_and_the_shot_moves_on():
    scene, _, shots, ctx = setup()
    row = {"version": 1, "prose": "A prompt."}
    tool.run(tool.Args(mode="prompt", scene_id=scene["id"], shot_id=shots[1]["id"], prompt=row), ctx)
    (saved,) = ctx.ports.scenes.prompts  # type: ignore[union-attr]
    assert saved["shot_id"] == shots[1]["id"] and saved["production_id"] == scene["production_id"]
    assert next(s for s in ctx.ports.scenes.shot_rows if s["id"] == shots[1]["id"])["status"] == "prompt"  # type: ignore[union-attr]
    with pytest.raises(ToolRefused, match="another shot"):
        tool.run(tool.Args(mode="prompt", scene_id=scene["id"], shot_id=shots[1]["id"],
                           prompt={"shot_id": shots[0]["id"]}), ctx)


def test_the_arguments_must_say_what_they_need():
    with pytest.raises(ValidationError, match="shot_id"):
        tool.Args(mode="design", scene_id="s")
    with pytest.raises(ValidationError, match="prompt row"):
        tool.Args(mode="prompt", scene_id="s", shot_id="x")
