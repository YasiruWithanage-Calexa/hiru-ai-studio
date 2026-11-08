"""The system (plan/2026-11-08e phase 3): the lab's two rehearsals as product tests. A scripted model plays run 3
(stage 1) and
pass 5 (stage 2) through the REAL agents, loop, code tools, checks, meter and storage step; no model is called."""

from __future__ import annotations

import re
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from contracts.raphael import checks, pack
from contracts.raphael.money import Meter
from contracts.raphael.scene import Brief
from hiru_ai.core import llm
from hiru_ai.systems.raphael.raphael_shot_planner import graph
from hiru_ai.systems.raphael.raphael_shot_planner import scene as raphael
from tests.raphael import gold, world
from tests.raphael.world import World


def planner(w: World, *, cap: float = 2, meter: Meter | None = None) -> raphael.Planner:
    """A planner for the world's scene, built the way the graph builds it."""
    row = w.row()
    lines = w.scenes.lines(row["id"])
    script, line_ids = raphael.script_of(
        row, lines, cast=["Kasun", "Anudi", "Father"], others=[], place="A roadside", objects=[]
    )
    production = {
        "style_note": "Cinematic Sri Lankan drama.",
        "rules": [],
        "people": [
            {"name": n, "code": c, "look": f"{n}, 25", "voice": "", "essence": "a person"}
            for n, c in world.PEOPLE.items()
        ],
    }
    context = {
        "heading": "EXT. ROAD",
        "note": "",
        "episode_title": "Ep 1",
        "synopsis": "",
        "before": "",
        "after": "",
        "place": "",
    }
    return raphael.Planner(
        w.ctx(), script, number=1, line_ids=line_ids, production=production, context=context, cap=cap, meter=meter
    )


def hashes(stored_clips: list) -> dict[str, str]:
    return {c.id: c.model_dump_json() for c in stored_clips}


# ── the whole scene ──────────────────────────────────────────────────────────────────────────────


def test_a_scene_goes_through_both_stages_and_finishes() -> None:
    w = World()
    with llm.use_models(world.model_for(world.stage1_turns(), world.stage2_turns())):
        done = planner(w).plan(previous={}, job_id="j1")
    stored = done.stored
    assert (stored.stage1, stage2 := stored.stage2) == ("finished", "finished") and stored.stopped == ""
    assert len(stored.musts()) == 13 and len(stored.extras()) == 8 and stored.seconds.take_s == 112
    assert stored.seconds.target_s == 60 and stored.seconds.cap_s == 120 and stored.cap == 2
    assert len(stored.blend_notes) == 8 and len(stored.review) == len(stored.edit.moments if stored.edit else [])
    assert stored.report["turns"] == {"stage1": 6, "stage2": 2} and stage2 == "finished"
    brief = gold.brief()
    work = gold.final()
    work.clips = stored.clips
    work.edit = stored.edit
    assert checks.blocking(checks.check_stage2(brief, work, cap=2)) == []


def test_stage_2_leaves_the_must_clips_exactly_as_stage_1_made_them() -> None:
    w = World()
    with llm.use_models(world.model_for(world.stage1_turns(), world.stage2_turns())):
        done = planner(w).plan(previous={}, job_id="j1")
    stage1_only = World()
    with llm.use_models(world.model_for(world.stage1_turns())):
        first = planner(stage1_only).plan(previous={}, job_id="j0", only_stage1=True)
    assert hashes(done.stored.musts()) == hashes(first.stored.musts())


@pytest.mark.parametrize("cap", [1.5, 2, 2.5, 3])
def test_stage_2s_room_is_the_cap_minus_what_stage_1_used(cap: float) -> None:
    w = World()
    seen: list[str] = []
    model = world.model_for(world.stage1_turns(), [])
    with llm.use_models(model):
        planner(w, cap=cap).plan(previous={}, job_id="j1")
    openings = [
        m.content
        for call_ in model.calls
        for m in call_
        if getattr(m, "type", "") == "human" and "<room>" in str(m.content)
    ]
    assert openings, "stage 2 was never given its room"
    seen.append(str(openings[0]))
    room = re.search(r"CAP: ([\d.]+) s of takes .*?: ([\d.]+) s left for cinematic clips", seen[0])
    assert room is not None
    assert float(room.group(1)) == 60 * cap and float(room.group(2)) == 60 * cap - 70


def test_stage_2_failing_leaves_stage_1_saved_whole() -> None:
    w = World()
    # nothing left for stage 2: the model "cannot be reached"
    with llm.use_models(world.model_for(world.stage1_turns())):
        done = planner(w).plan(previous={}, job_id="j1")
    stored = done.stored
    assert (stored.stage1, stored.stage2) == ("finished", "stopped") and "model failed" in stored.stopped
    assert len(stored.musts()) == 13 and stored.extras() == [] and stored.editor_notes
    assert {c.id for c in stored.musts()} == {c.id for c in gold.stage1().clips}


def test_a_stage_2_that_stops_keeps_only_cinematic_clips_that_pass_the_checks() -> None:
    w = World()
    # the pass writes its 8 clips and then the model goes away: no finish, no review
    with llm.use_models(world.model_for(world.stage1_turns(), world.stage2_turns(finish=False))):
        done = planner(w).plan(previous={}, job_id="j1")
    stored = done.stored
    assert stored.stage2 == "stopped" and stored.review == []
    # code writes a plain note for each, honestly marked
    assert len(stored.extras()) == 8 and len(stored.blend_notes) == 8
    assert all("stopped before it wrote a note" in n for n in stored.blend_notes)


def test_a_stage_2_that_stops_over_the_cap_drops_nice_clips_first() -> None:
    w = World()
    with llm.use_models(world.model_for(world.stage1_turns(), world.stage2_turns(finish=False))):
        done = planner(w, cap=1.5).plan(previous={}, job_id="j1")  # 90 s: 70 s of must leaves 20 s for 42 s of extras
    stored = done.stored
    assert stored.seconds.take_s <= 90 and stored.seconds.cap_s == 90 and stored.cap == 1.5
    assert stored.seconds.take_s == 90 and stored.seconds.cinematic_s == 20  # the room, filled
    assert {c.id for c in stored.extras()} == {"c15", "c16", "c17", "c18"}  # the nice clips went first, then the latest
    assert all(c.priority == "should" for c in stored.extras())


# ── the stops ────────────────────────────────────────────────────────────────────────────────────


def test_the_run_cap_stops_a_run_and_a_stopped_stage_1_with_nothing_to_keep_fails() -> None:
    w = World()
    spent = Meter(cap_usd=0.0001)
    with llm.use_models(world.model_for(world.stage1_turns())):
        with pytest.raises(raphael.Failed) as err:
            planner(w, meter=spent).plan(previous={}, job_id="j1")
    assert "limit" in str(err.value) and "classic planner" in str(err.value)


def test_a_stage_1_that_stops_with_clips_is_saved_marked_stopped_and_stage_2_is_skipped() -> None:
    w = World()
    turns = world.stage1_turns(finish=False)  # edit plan and clips, then the model runs out of replies
    with llm.use_models(world.model_for(turns)):
        done = planner(w).plan(previous={}, job_id="j1")
    stored = done.stored
    assert (stored.stage1, stored.stage2) == ("stopped", "skipped") and stored.stopped
    assert stored.musts() and stored.extras() == []


def test_the_turn_cap_ends_a_conversation_that_does_not_finish() -> None:
    w = World()
    spin = [world.call("read_bin", {"moment": 0}, n) for n in range(25)]
    with llm.use_models(world.model_for(world.stage1_turns(finish=False)[:1], spin)):
        with pytest.raises(raphael.Failed):  # an edit plan and no clips: nothing to keep
            planner(w).plan(previous={}, job_id="j1")


def test_a_model_with_no_price_is_refused_before_any_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI__MODEL_RAPHAEL", "gpt-unknown")
    from hiru_ai.core.settings import get_settings

    get_settings.cache_clear()
    try:
        w = World()
        with llm.use_models(world.model_for(world.stage1_turns())):
            with pytest.raises(raphael.Failed) as err:
                planner(w).plan(previous={}, job_id="j1")
        assert "no price" in str(err.value)
    finally:
        get_settings.cache_clear()


def test_the_meter_counts_each_reply_and_stops_at_the_cap() -> None:
    meter = Meter()
    meter.charge("gpt-5", 1_000_000, 0, 1_000_000)  # 1.25 + 10.00
    assert meter.spent == pytest.approx(11.25) and meter.exhausted
    with pytest.raises(Exception, match="cap"):
        meter.guard()


# ── "More cinematic" and the hash ────────────────────────────────────────────────────────────────


def test_more_cinematic_runs_stage_2_alone_over_the_stored_must_bin() -> None:
    w = World()
    stored = world.stored_stage1(w)
    with llm.use_models(world.model_for(world.stage2_turns())):
        done = planner(w, cap=2.5).more_cinematic(stored, previous={}, job_id="j2")
    after = done.stored
    assert after.stage2 == "finished" and after.cap == 2.5 and len(after.extras()) == 8
    assert hashes(after.musts()) == hashes(stored.musts()) and after.report["turns"]["stage1"] == 0


def test_more_cinematic_needs_a_finished_stage_1() -> None:
    w = World()
    stored = world.stored_stage1(w).model_copy(update={"stage1": "stopped"})
    with pytest.raises(raphael.Failed):
        planner(w).more_cinematic(stored, previous={}, job_id="j2")


def test_the_input_hash_changes_with_the_scene_the_note_and_the_cap() -> None:
    w = World()
    base = planner(w).input_hash()
    assert planner(w).input_hash() == base and planner(w, cap=3).input_hash() != base
    other = planner(w)
    other.context = {**other.context, "note": "make it tighter"}
    assert other.input_hash() != base


def test_the_openings_carry_no_money_and_the_stage_2_room_is_in_seconds() -> None:
    brief = Brief(gold.scene(), 60)
    first = pack.opening_stage1({"people": []}, {}, brief)
    second = pack.opening_stage2({"people": []}, {}, brief, gold.stage1(), 2)
    for text in (first, second):
        assert "$" not in text and "cost" not in text.lower() and "credit" not in text.lower()
    assert "<length>" in first and "<room>" in second and "<must_bin>" in second and "<looks>" in second


# ── the graph over the fakes ─────────────────────────────────────────────────────────────────────


def run_graph(w: World, payload: Any, *turns: list[AIMessage]) -> dict[str, Any]:
    with llm.use_models(world.model_for(*turns)):
        return graph.run(payload, w.ctx())


def test_the_graph_plans_a_scene_and_writes_a_clip_per_shot() -> None:
    w = World()
    result = run_graph(w, w.payload(replan=True), world.stage1_turns(), world.stage2_turns())
    assert result["scenes"] == 1 and result["shots"] == 21 and result["failed"] == 0
    shots = w.shots()
    assert len(shots) == 21 and all(s["planner"] == "raphael" and s["ir"] and s["design"]["pins"] for s in shots)
    assert [s["number"] for s in shots] == list(range(1, 22))
    stored = w.stored()
    assert stored.stage2 == "finished" and w.row()["status"] == "split"
    assert {s["slate"] for s in shots} == {c.slate for c in stored.clips}
    assert sum(1 for s in shots if s["stage"] == 2) == 8 and all(s["anchor"] for s in shots if s["stage"] == 2)
    slates = {s["slate"] for s in shots}
    # anchors are slates, as a person reads
    assert all(a in slates for s in shots if s["stage"] == 2 for a in s["anchor"])


def test_each_line_is_bound_to_the_clip_that_performs_it() -> None:
    w = World()
    run_graph(w, w.payload(replan=True), world.stage1_turns(), world.stage2_turns())
    shots = {s["id"]: s for s in w.shots()}
    bound = [ln for ln in w.scenes.line_rows if ln.get("shot_id")]
    assert len(bound) == len(w.line_rows)  # every line has its performer
    for ln in bound:
        shot = shots[ln["shot_id"]]
        assert shot["priority"] == "must" and shot["stage"] == 1


def test_a_scene_whose_input_is_unchanged_makes_no_call() -> None:
    w = World()
    run_graph(w, w.payload(replan=True), world.stage1_turns(), world.stage2_turns())
    before = hashes(w.stored().clips)
    model = world.model_for([])  # no reply at all: a call would fail
    with llm.use_models(model):
        result = graph.run(w.payload(), w.ctx())
    assert result["scenes"] == 0 and result["skipped"] == 1 and model.calls == []
    assert hashes(w.stored().clips) == before


def test_a_cap_in_the_delivery_beats_the_productions_default() -> None:
    w = World(settings={"raphael_length_cap": 3})
    run_graph(w, w.payload(replan=True, edit={"cap": 1.5}), world.stage1_turns(), world.stage2_turns(finish=False))
    assert w.stored().cap == 1.5
    w2 = World(settings={"raphael_length_cap": 3})
    run_graph(w2, w2.payload(replan=True), world.stage1_turns(), world.stage2_turns())
    assert w2.stored().cap == 3


def test_the_cinematic_job_runs_stage_2_alone_and_replaces_the_cinematic_clips() -> None:
    from contracts.jobs import JobKind

    w = World()
    run_graph(w, w.payload(replan=True), world.stage1_turns(), world.stage2_turns())
    musts = hashes(w.stored().musts())
    run_graph(
        w, w.payload(JobKind.CINEMATIC_SCENE_RAPHAEL, edit={"stage": "cinematic", "cap": 2.5}), world.stage2_turns()
    )
    stored = w.stored()
    assert stored.cap == 2.5 and hashes(stored.musts()) == musts and len(stored.extras()) == 8
    assert len(w.shots()) == 21


def test_an_approved_scene_is_never_touched() -> None:
    w = World(status="approved")
    result = run_graph(w, w.payload(replan=True), world.stage1_turns(), world.stage2_turns())
    assert result["scenes"] == 0 and w.shots() == []


def test_with_no_model_the_job_fails_clearly_and_names_the_classic_planner() -> None:
    w = World()
    result = graph.run(w.payload(replan=True), w.ctx())
    assert "classic planner" in result["failed"]


def test_the_graph_draws() -> None:
    assert graph.blank().get_graph().draw_mermaid()
