"""sable_shot_try (plan/2026-11-13 phase 8): the open scene's rows as the row kernel numbers them; a trial on a copy."""
from __future__ import annotations

import json

from hiru_ai.core.testing import example_of, run_example


def test_the_example_lands_on_a_copy_and_nothing_is_saved():
    case = example_of("sable_shot_try")
    before = json.dumps(case["fixtures"]["shots"], sort_keys=True)
    out, ctx = run_example("sable_shot_try")
    assert out.applied == 1 and out.refused == 0 and out.changes == ["S01 · take: 6 s → 8 s"]
    assert out.timing["takes_s"] == out.timing["was_s"] + 2
    assert json.dumps(ctx.ports.scenes.shot_rows, sort_keys=True) == before


def test_with_no_ops_it_shows_the_blocks_with_line_codes_and_the_clips():
    out, _ = run_example("sable_shot_try", {"ops": []})
    assert out.tried == [] and "b1 line L1" in out.shots and "S02" in out.shots
