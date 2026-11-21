"""plan/2026-11-20c D11 (b): a Zora or Sable save whose clips' camera design changed gets the Camera agent for THOSE
clips, in ONE one-shot call with the scene as context (`core.coverage_rows.finish_designs`); untouched clips keep their
design; with the agent off (or no `ctx`), no call. Fakes only: the agent's door is stubbed."""
from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from hiru_ai.core import camera, coverage_rows
from tests.zora.rows_world import Recorded, RowsWorld


def stub(monkeypatch: pytest.MonkeyPatch, *, on: bool = True) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake(ctx: Any, scene: Any, prod: Any, **kw: Any) -> camera.Designed:
        calls.append({"scene": [s.id for s in scene.shots], **kw})
        out = camera.Designed()
        for sid in kw.get("focus") or []:
            shot = next(s for s in scene.shots if s.id == sid)
            out.designs[sid] = {**(shot.row.get("design") or {}), "camera": {"state": "designed", "move": "push_in"}}
        return out

    monkeypatch.setattr(camera, "on", lambda: on)
    monkeypatch.setattr(camera, "design", fake)
    return calls


def plan_of(w: RowsWorld, changed: list[str]) -> tuple[Any, coverage_rows.Plan]:
    world = coverage_rows.read(w.ctx(), UUID(w.production), UUID(w.scene_id))
    assert not isinstance(world, str)
    rows = [dict(r) for r in world.shot_rows]
    upsert = [r for r in rows if str(r["id"]) in changed]
    return world, coverage_rows.Plan(upsert=upsert, removed=[], lines=[], rows=rows, all_lines=list(world.lines),
                                     designs=list(changed), touched=list(changed))


def test_the_clips_whose_design_changed_get_one_camera_call_the_rest_keep_theirs(
        monkeypatch: pytest.MonkeyPatch) -> None:
    calls = stub(monkeypatch)
    w = RowsWorld()
    ids = [str(r["id"]) for r in w.scenes.shots(w.scene_id)]
    world, plan = plan_of(w, ids[:2])
    before = {str(r["id"]): r.get("design") for r in plan.rows}
    warnings = coverage_rows.finish_designs(world, plan, w.ctx())
    assert warnings == [] and len(calls) == 1 and calls[0]["focus"] == ids[:2]
    assert calls[0]["scene"] == ids  # the whole scene is the context
    rows = {str(r["id"]): r for r in plan.rows}
    assert all(rows[i]["design"]["camera"]["state"] == "designed" for i in ids[:2])
    assert all(rows[i].get("design") == before[i] for i in ids[2:])
    assert {str(u["id"]) for u in plan.upsert} == set(ids[:2])
    assert all(u["design"]["camera"]["state"] == "designed" for u in plan.upsert)


def test_without_a_ctx_or_with_the_agent_off_no_call(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = stub(monkeypatch)
    w = RowsWorld()
    ids = [str(r["id"]) for r in w.scenes.shots(w.scene_id)]
    world, plan = plan_of(w, ids[:1])
    coverage_rows.finish_designs(world, plan)
    assert calls == []
    calls = stub(monkeypatch, on=False)
    world, plan = plan_of(w, ids[:1])
    coverage_rows.finish_designs(world, plan, w.ctx())
    assert calls == []


def test_with_the_agent_off_a_turn_makes_no_camera_call(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = stub(monkeypatch, on=False)
    w = RowsWorld()
    w.turn("Make S01 a wide, 6 seconds.", Recorded())
    assert calls == []
