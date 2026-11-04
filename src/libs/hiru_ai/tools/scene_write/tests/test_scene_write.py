from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from tests.hiru_ai.steps_fixtures import run_ctx
from tests.services.director_chat.conftest import fixture_scene

from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ToolRefused
from hiru_ai.tools.scene_write import tool


def setup() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], RunContext]:
    scene, lines, shots = fixture_scene(0)
    return scene, lines, shots, run_ctx(scene, lines, shots, canon=[])


def write(ctx: RunContext, scene: dict[str, Any], **kw: Any) -> tool.Result:
    return tool.run(tool.Args(scene_id=scene["id"], **kw), ctx)


def test_an_agent_renumbers_a_shot_and_changes_the_scene_status():
    scene, _, shots, ctx = setup()
    out = write(ctx, scene, shots=[{**shots[0], "framing": "CU"}], scene_fields={"status": "split"})
    assert out.shots == 1
    stored = ctx.ports.scenes
    assert next(s for s in stored.shot_rows if s["id"] == shots[0]["id"])["framing"] == "CU"  # type: ignore[union-attr]


def test_removing_a_shot_of_this_scene_removes_it():
    scene, _, shots, ctx = setup()
    write(ctx, scene, removed_shots=[shots[-1]["id"]])
    assert shots[-1]["id"] not in {s["id"] for s in ctx.ports.scenes.shot_rows}  # type: ignore[union-attr]


def test_an_agent_cannot_reword_a_line():
    scene, lines, _, ctx = setup()
    with pytest.raises(ToolRefused, match="own words"):
        write(ctx, scene, lines=[{**lines[0], "text": "an improved line"}])
    assert ctx.ports.scenes.lines(scene["id"])[0]["text"] == lines[0]["text"]  # type: ignore[union-attr]


def test_an_agent_cannot_add_or_remove_a_line():
    scene, lines, _, ctx = setup()
    with pytest.raises(ToolRefused):
        write(ctx, scene, lines=[{"id": str(uuid4()), "scene_id": scene["id"], "text": "new", "speaker": "X"}])
    with pytest.raises(ToolRefused, match="remove"):
        write(ctx, scene, removed_lines=[lines[0]["id"]])


def test_a_person_may_reword_a_line_and_the_id_stays():
    scene, lines, _, ctx = setup()
    write(ctx, scene, lines=[{**lines[0], "text": "their own sentence"}], by="person")
    assert ctx.ports.scenes.lines(scene["id"])[0]["text"] == "their own sentence"  # type: ignore[union-attr]
    assert ctx.ports.scenes.lines(scene["id"])[0]["id"] == lines[0]["id"]  # type: ignore[union-attr]


def test_a_translation_keeps_its_original_and_cannot_touch_the_speaker():
    scene, lines, _, ctx = setup()
    translated = {**lines[0], "text": "Hello there", "source_text": lines[0]["text"], "source_lang": "si"}
    write(ctx, scene, lines=[translated], by="translator")
    assert ctx.ports.scenes.lines(scene["id"])[0]["source_text"] == lines[0]["text"]  # type: ignore[union-attr]
    with pytest.raises(ToolRefused):
        write(ctx, scene, lines=[{**translated, "speaker": "Someone Else"}], by="translator")
    with pytest.raises(ToolRefused):  # a "translation" that does not keep the original is a rewrite
        write(ctx, scene, lines=[{**lines[1], "text": "rewritten"}], by="translator")


def test_it_will_not_remove_a_shot_or_line_of_another_scene():
    scene, _, _, ctx = setup()
    with pytest.raises(ToolRefused, match="shot to remove"):
        write(ctx, scene, removed_shots=[str(uuid4())])
    with pytest.raises(ToolRefused, match="line to remove"):
        write(ctx, scene, removed_lines=[str(uuid4())], by="person")


def test_it_will_not_write_a_shot_of_another_scene_or_production():
    scene, _, shots, ctx = setup()
    with pytest.raises(ToolRefused, match="another scene"):
        write(ctx, scene, shots=[{**shots[0], "scene_id": str(uuid4())}])
    with pytest.raises(ToolRefused, match="another production"):
        write(ctx, scene, shots=[{**shots[0], "production_id": str(uuid4())}])


def test_a_scene_cannot_be_moved():
    scene, _, _, ctx = setup()
    with pytest.raises(ToolRefused, match="production_id"):
        write(ctx, scene, scene_fields={"production_id": str(uuid4())})
