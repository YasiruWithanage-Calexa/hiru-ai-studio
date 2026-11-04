from __future__ import annotations

import pytest

from hiru_ai.core.errors import PortMissing, ToolRefused
from hiru_ai.core.testing import example_ctx, example_of, run_example
from hiru_ai.tools.scene_read import tool


def test_only_the_parts_asked_for_come_back():
    out, _ = run_example("scene_read", {"include": ["shots"]})
    assert out.scene == "E1S2" and out.shots and out.script is None and out.lines is None and out.canon is None
    assert out.shots[0]["shot"] == "S01" and out.shots[0]["framing"] == "MCU" and "title" not in out.shots[0]


def test_the_script_keeps_every_spoken_line_word_for_word():
    out, ctx = run_example("scene_read", {"include": ["script"]})
    spoken = [b for b in out.script or [] if b["kind"] == "dialogue"]
    stored = [ln["text"] for ln in ctx.ports.scenes.line_rows]
    assert [b["text"] for b in spoken] == stored and spoken[0]["speaker"] == "Kasun"


def test_lines_say_which_shot_carries_them():
    out, _ = run_example("scene_read", {"include": ["lines"]})
    assert [ln["shot"] for ln in out.lines or []] == ["S01", "S02"]


def test_a_range_of_shots_narrows_the_plan():
    out, _ = run_example("scene_read", {"include": ["shots"], "shots": "S02"})
    assert [s["shot"] for s in out.shots or []] == ["S02"]
    both, _ = run_example("scene_read", {"include": ["shots"], "shots": "S01-S02"})
    assert len(both.shots or []) == 2
    with pytest.raises(ToolRefused, match="not a shot"):
        run_example("scene_read", {"include": ["shots"], "shots": "the last one"})


def test_canon_gives_codes_not_cards():
    out, _ = run_example("scene_read", {"include": ["canon"]})
    assert {c["code"] for c in out.canon or []} == {"C01", "C03", "L01"}
    assert all(set(c) == {"code", "name", "kind"} for c in out.canon or [])


def test_reading_and_staging_are_short_until_detailed():
    short, _ = run_example("scene_read", {"include": ["reading", "staging"]})
    assert set(short.reading or {}) <= {"about", "value", "tone", "ending"} and short.staging["marks"] == 2
    full, _ = run_example("scene_read", {"include": ["reading", "staging"], "response_format": "detailed"})
    assert "units" in (full.reading or {}) and "marks" in (full.staging or {}) and len(full.staging["marks"]) == 2


def test_the_scene_defaults_to_the_runs_and_another_production_is_never_reachable():
    out, _ = run_example("scene_read", {"scene": None, "include": ["shots"]})
    assert out.scene == "E1S2"
    with pytest.raises(ToolRefused, match="no scene"):
        run_example("scene_read", {"scene": "E7S1"})
    with pytest.raises(ToolRefused, match="no scene in scope"):
        run_example("scene_read", {"scene": None}, scene_id=None)


def test_a_run_without_the_scene_port_says_which_port():
    from dataclasses import replace

    ctx = example_ctx(example_of("scene_read"))
    with pytest.raises(PortMissing, match="scenes"):
        tool.run(tool.Args(), replace(ctx, ports=replace(ctx.ports, scenes=None)))
