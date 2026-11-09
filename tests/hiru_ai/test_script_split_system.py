"""The script_split system against the legacy pipeline on what the Phase 0 fixtures do not reach: the time budget that
hands scenes to another delivery, the model's reading and staging, and each code half (the steps) against the function
it was ported from. Same inputs on both engines, the whole outcome compared.
"""
from __future__ import annotations

import copy
from typing import Any

import pytest
from script_split.engine import beats as legacy_beats
from script_split.engine import pipeline as legacy
from script_split.engine import planner as legacy_planner
from script_split.engine import reading as legacy_reading
from script_split.engine import staging as legacy_staging

from contracts import beats as screen_beats
from contracts import sceneplan
from contracts.shotplan import fit
from hiru_ai.core import parts
from hiru_ai.systems.script_split import graph
from tests.parity.adapters import run_case
from tests.parity.harness import outcome
from tests.services.script_split import test_split as t

SCENES = [0, 1, 2, 3, 4, 5]


def step(ident: str) -> Any:
    return parts.step(ident)


def same(inp: dict[str, Any], model: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run one case on both engines; they must agree. -> the (graph) outcome."""
    model = model or {}
    got = {engine: outcome(run_case("script_split", copy.deepcopy(inp), copy.deepcopy(model), engine))
           for engine in ("legacy", "graph")}
    assert got["graph"] == got["legacy"]
    return got["graph"]


# ── the time budget ────────────────────────────────────────────────────────────────────────


def test_past_the_time_budget_the_rest_goes_to_another_delivery(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(legacy, "TIME_BUDGET_S", -1.0)  # every wave after the first is "too late"
    monkeypatch.setattr(graph, "TIME_BUDGET_S", -1.0)
    got = same({"scenes": [0, 1, 2], "state": {"build": True}})
    assert got["result"]["scenes"] == 1 and got["result"]["continued"] == 2
    handoff = got["jobs"]["advanced"][0]
    assert handoff["again"] is True and handoff["state"]["build"] is True and len(handoff["state"]["scene_ids"]) == 2
    assert got["jobs"]["status"] == "running"


# ── a model that reads and places the scene ────────────────────────────────────────────────

BEATS = {"blocks": [{"block": 0, "screen": "move", "events": 2}, {"block": 2, "screen": "act", "events": 2}]}
READING = {
    "about": "A son comes home.", "value": {"start": "calm", "end": "tension"}, "tone": "quiet, tense",
    "units": [{"from_block": 0, "to_block": 3, "wants": [{"character": "Nimal", "verb": "to be let in"}],
               "turn_block": 3}],
    "subtext": [], "ending": "Nimal at the table.",
    "breath": [{"after_block": 3, "kind": "reaction", "who": "Nimal", "seconds": 1.5, "priority": 1,
                "why": "the turn at the end"}]}
# plan/2026-11-09: the stager's answer carries the state ledger's fields too (strict mode: every one, "" allowed)
LEDGER = {"posture": "", "left_hand": "", "right_hand": "", "condition": "", "wearing": ""}
STAGING = {"zones": ["door", "stove"], "props": [], "marks": [
    {"block": 0, "who": "Kamala", "zone": "stove", "facing": "", "frame_side": "", "holding": "", **LEDGER},
    {"block": 1, "who": "Nimal", "zone": "door", "facing": "", "frame_side": "", "holding": "", **LEDGER},
    {"block": 3, "who": "Nimal", "zone": "stove", "facing": "", "frame_side": "", "holding": "", **LEDGER}]}
PLAN = {"shots": [
    {"start": 0, "end": 2, "framing": "WIDE", "title": "Nimal at the door", "sound_mode": "dialogue", "duration": 8,
     "camera_link": "cut"},
    {"start": 2, "end": 4, "framing": "CU", "title": "Kamala keeps cooking", "sound_mode": "dialogue", "duration": 6,
     "camera_link": "cut"}]}
REVIEW = {"acceptable": True, "notes": []}


def test_the_models_beats_reading_and_staging_give_the_same_scene_on_both_engines():
    got = same({"scenes": [0]}, {"enabled": True, "replies": {
        "beat_screen": [BEATS], "scene_reading": [READING], "scene_staging": [STAGING],
        "shot_plan": [PLAN], "shot_review": [REVIEW] * 3}})
    scene = next(iter(got["scene_rows"].values()))
    assert scene["reading"]["by"] == "model" and scene["staging"]["by"] == "model"
    assert [c["schema"] for c in got["llm"]] == [
        "beat_screen", "scene_reading", "scene_staging", "shot_plan", "shot_review", "shot_review", "shot_review"]


def test_an_unusable_reading_or_staging_falls_back_on_both_engines():
    got = same({"scenes": [0]}, {"enabled": True, "replies": {
        "beat_screen": [{"blocks": []}], "scene_reading": [{**READING, "about": "", "units": []}],
        "scene_staging": [{"zones": [], "marks": [], "props": []}], "shot_plan": [PLAN], "shot_review": [REVIEW] * 3}})
    scene = next(iter(got["scene_rows"].values()))
    assert scene["reading"]["by"] == "rules" and "staging" not in scene


def test_a_persons_reading_and_map_are_kept_on_both_engines():
    def person(by: str) -> dict[str, Any]:
        stored = {**READING, "by": by, "for_version": 1, "basis": "x", "units": [], "written_at": None}
        return {"0": {"reading": stored}}

    got = same({"scenes": [0], "scene_fields": person("person")}, {"enabled": True, "replies": {
        "shot_plan": [PLAN], "shot_review": [REVIEW] * 3}})
    assert next(iter(got["scene_rows"].values()))["reading"]["by"] == "person"


# ── each code half against the function it was ported from ─────────────────────────────────


def scene_and_lines(n: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return t.scene_from_fixture(n)


@pytest.mark.parametrize("n", SCENES)
@pytest.mark.parametrize("envelope", [12, 24, 60])
@pytest.mark.parametrize("fixed", [None, 8])
def test_the_rules_plan_is_the_legacy_one(n: int, envelope: int, fixed: int | None):
    scene, lines = scene_and_lines(n)
    items = legacy.items_for(scene, lines)
    want_items, want_shots = legacy_planner.rules_plan(items, envelope_s=envelope, fixed_seconds=fixed)
    got_items, got_shots = step("rules_plan").rules_plan(items, envelope_s=envelope, fixed_seconds=fixed)
    assert got_items == want_items and got_shots == want_shots
    assert step("rules_plan").plan_by_rules(items) == legacy_planner.plan_by_rules(items)


@pytest.mark.parametrize("n", SCENES)
def test_prepare_reads_blocks_like_the_legacy_function(n: int):
    scene, lines = scene_and_lines(n)
    cast = ["Nimal", "Kamala"]

    class Off:
        enabled = False

    want = legacy.prepare(copy.deepcopy(scene), lines, Off(), cast)
    got = step("scene_prep").prepare(copy.deepcopy(scene), lines, None, cast)
    assert got == want

    def ask(items: list[Any]) -> dict[str, Any]:
        return BEATS

    class On:
        enabled = True

        def json(self, **kw: Any) -> dict[str, Any]:
            return BEATS

    want = legacy.prepare(copy.deepcopy(scene), lines, On(), cast)
    got = step("scene_prep").prepare(copy.deepcopy(scene), lines, ask, cast)
    assert got == want


def test_classify_keeps_the_rules_for_a_block_the_model_leaves_out_and_for_a_failed_call():
    scene, lines = scene_and_lines(0)
    items = sceneplan.items_for(scene["script"], lines)
    prep = step("scene_prep")
    answer = {"blocks": [{"block": 0, "screen": "move", "events": 9}, {"block": 1, "screen": "act", "events": 1},
                         {"block": 2, "screen": "nonsense", "events": 1}, {"block": "x"}]}
    assert prep.classify(lambda items: answer, items) == legacy_beats.classify(lambda s, u: answer, items)

    def boom(*args: Any) -> dict[str, Any]:
        raise RuntimeError("down")

    assert prep.classify(boom, items) == legacy_beats.classify(boom, items)
    assert prep.classify(None, items) == legacy_beats.classify(None, items)


@pytest.mark.parametrize("n", [0, 2, 3])
def test_the_reading_and_the_map_are_made_and_kept_like_the_legacy_functions(n: int):
    scene, lines = scene_and_lines(n)
    items = sceneplan.items_for(scene["script"], lines)
    cast = ["Nimal", "Kamala"]
    prep = step("scene_prep")
    for answer in (READING, {**READING, "units": [], "about": ""}):
        want = legacy_reading.reading_for(copy.deepcopy(scene), items, lambda s, u, a=answer: a, cast)
        got = prep.reading_for(copy.deepcopy(scene), items, lambda its, a=answer: a, cast)
        assert (got[0].model_copy(update={"written_at": None}), got[1]) == (
            want[0].model_copy(update={"written_at": None}), want[1])
    for answer in (STAGING, {"zones": [], "marks": [], "props": []}):
        want_s = legacy_staging.staging_for(copy.deepcopy(scene), items, lambda s, u, a=answer: a, cast)
        got_s = prep.staging_for(copy.deepcopy(scene), items, lambda its, a=answer: a, cast)
        strip = lambda m: None if m is None else m.model_copy(update={"written_at": None})  # noqa: E731
        assert (strip(got_s[0]), got_s[1]) == (strip(want_s[0]), want_s[1])
    assert prep.staging_for(copy.deepcopy(scene), items, None, cast) == (None, False)


def test_a_teleport_gets_one_removable_step_like_the_legacy_stage():
    scene, lines = scene_and_lines(0)
    prep = step("scene_prep")
    cast = ["Nimal", "Kamala"]
    names = {lines[0]["character_id"]: "Nimal", lines[1]["character_id"]: "Kamala"}
    script, items = prep.prepare(copy.deepcopy(scene), lines, None, cast)
    reading, _ = prep.reading_for(scene, items, None, cast)

    class On:
        enabled = True

        def json(self, **kw: Any) -> dict[str, Any]:
            return STAGING

    want = legacy.stage(copy.deepcopy(scene), lines, script, items, reading, On(), names)
    got = prep.stage(copy.deepcopy(scene), lines, script, items, reading, lambda its: STAGING, names)
    strip = lambda m: None if m is None else m.model_copy(update={"written_at": None})  # noqa: E731
    assert (got[0], got[1], got[2]) == (want[0], want[1], want[2]) and strip(got[3]) == strip(want[3])
    assert any(i.bridge for i in got[1]) or got[3] is not None  # something was placed


def test_the_context_and_the_written_rows_are_the_legacy_ones():
    scene, lines = scene_and_lines(1)
    prep, write = step("scene_prep"), step("split_write")
    episodes = {t.EP: {"title": "The Return", "synopsis": "Nimal comes home."}}
    neighbours = [{"id": f"s{i}", "episode_id": t.EP, "number": i, "heading": f"INT. {i}", "title": f"T{i}"}
                  for i in range(1, 5)]
    cards = [("Nimal", "the son"), ("Kamala", "")]
    want = legacy.scene_context(scene, episodes, neighbours, cards)
    got = prep.scene_context(scene, episodes, neighbours, cards)
    assert prep.context_text(got) == want.text()
    assert (got["before"], got["after"]) == (want.before, want.after)

    items = legacy.items_for(scene, lines)
    result = fit(items, legacy_planner.plan_by_rules(items), envelope_s=60)
    shots, line_rows = write.rows_for(scene, result, lines)
    assert len(shots) == len(result.shots) and [r["id"] for r in line_rows] == [ln["id"] for ln in lines]
    assert write.report(result, "rules", ["x"]) == legacy.report(result, "rules", ["x"])
    label = "Ep 01 Scene 2"
    assert write.continuity_notes(label, scene, lines) == legacy.continuity_notes(label, scene, lines)
    stats = write.episode_stats(result, scene)
    assert stats == legacy.episode_stats(result, scene)
    for tweak in ({}, {"envelope_s": 3}, {"off_screen": 2}, {"off_screen": 1}):
        assert write.episode_line(2, {**stats, **tweak}) == legacy.episode_line(2, {**stats, **tweak})


def test_location_notes_name_the_place_and_what_it_is():
    rows = [{"id": "L1", "name": "Kitchen", "current": {"card": {"summary": "a small hot room"}}},
            {"id": "L2", "name": "Gate", "current": None}]
    assert step("scene_prep").location_notes(rows) == {"L1": "Kitchen — a small hot room", "L2": "Gate"}


def test_the_script_is_marked_read_for_the_version():
    scene, lines = scene_and_lines(0)
    _, items = step("scene_prep").prepare(scene, lines, None, [])
    assert not screen_beats.is_stale(items, int(scene.get("script_version") or 1))
