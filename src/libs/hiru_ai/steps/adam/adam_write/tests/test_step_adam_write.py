"""adam_write: the gold master written as rows (plan/2026-11-04b §5.3). Nothing here calls a model or a database."""
from __future__ import annotations

from typing import Any

import pytest
from tests.adam import gold, stages

from contracts.adam.plan import Moment
from contracts.adam.stored import Removed, StoredPlan
from hiru_ai.core import parts
from hiru_ai.steps.adam.adam_write import logic, step

SCENE_ROW = {"id": "scene-1", "production_id": "prod-1", "status": "planned"}


def stored_of(name: str) -> StoredPlan:
    p = stages.master_with_stance(name)
    line_ids = {b["line_id"]: f"line-{b['line_id']}" for b in gold.scene(name)["blocks"] if b.get("line_id")}
    return StoredPlan(chosen=p.treatment.stance, analysis=p.analysis, treatment=p.treatment, moments=p.moments,
                      staging=p.staging, cards=p.cards, sound_map=p.sound_map, line_ids=line_ids)


def line_rows(name: str) -> list[dict[str, Any]]:
    rows = []
    for n, b in enumerate(b for b in gold.scene(name)["blocks"] if b.get("line_id")):
        rows.append({"id": f"line-{b['line_id']}", "production_id": "prod-1", "scene_id": "scene-1", "ord": n,
                     "speaker": b["speaker"], "character_id": f"char-{b['speaker']}", "text": b["text"],
                     "delivery": b.get("delivery", "")})
    return rows


def fit_of(name: str, stored: StoredPlan) -> dict[str, Any]:
    plan = stored.plan().model_dump(mode="json", by_alias=True)
    return dict(parts.module("step", "adam_fit", "step").run({"scene": gold.scene(name), "plan": plan}))


def written(name: str = "phone_call") -> dict[str, Any]:
    stored = stored_of(name)
    return step.run({"scene": SCENE_ROW, "lines": line_rows(name), "stored": stored.data(),
                     "fit": fit_of(name, stored), "notes": ["[audience, low] card 1: x"]})


def test_the_test_scene_is_thirteen_shots_of_66_seconds_each_with_its_card():
    out = written()
    shots = out["shots"]
    assert [s["number"] for s in shots] == list(range(1, 14)) and sum(s["duration_s"] for s in shots) == 66
    assert all(s["planner"] == "adam" and s["card"]["number"] == s["number"] for s in shots)
    assert all(s["framing"] in ("WIDE", "MS", "MCU", "CU", "TWO", "OTS", "INSERT") for s in shots)
    assert [s["start_s"] for s in shots] == [sum(x["duration_s"] for x in shots[:i]) for i in range(13)]
    assert all(s["block_start"] <= s["block_end"] for s in shots)


def test_every_line_is_bound_to_a_shot_once_with_where_it_starts_and_what_overruns():
    out = written()
    assert len(out["lines"]) == 4 and all(ln["shot_id"] for ln in out["lines"])
    by_id = {s["id"]: s for s in out["shots"]}
    for ln in out["lines"]:
        assert ln["words"] > 0 and ln["start_s"] >= by_id[ln["shot_id"]]["start_s"] and ln["overrun_s"] == 0
    assert [ln["ord"] for ln in out["lines"]] == [0, 1, 2, 3]


def test_the_sound_of_a_shot_follows_its_lines_and_its_silence():
    out = written()
    modes = {s["number"]: s["sound_mode"] for s in out["shots"]}
    assert modes[9] == "dialogue" and modes[8] == "silent"  # "I'll come, Thaththe" on her; the break is a silence
    assert modes[3] == "ambient" and out["shots"][8]["speaker_id"] == "char-Anudi"


def test_a_line_played_over_a_listener_makes_a_voiceover_shot_and_the_speaker_is_not_the_shots_speaker():
    stored = stored_of("phone_call")
    cards = [c.model_copy(update={"lines": [ln.model_copy(update={"on_speaker": False, "over_whom": "Dasun"})
                                            for ln in c.lines]}) if c.number == 9 else c for c in stored.cards]
    stored = stored.model_copy(update={"cards": cards})
    out = step.run({"scene": SCENE_ROW, "lines": line_rows("phone_call"), "stored": stored.data(),
                    "fit": fit_of("phone_call", stored)})
    shot = out["shots"][8]
    assert shot["sound_mode"] == "voiceover" and shot["speaker_id"] is None and shot["word_target"] > 0


def test_the_fit_report_has_the_classic_shape_and_the_stored_plan_comes_back_whole():
    fields = written()["fields"]
    report = fields["fit_report"]
    assert report["planner"] == "adam" and report["total_s"] == 66 and report["critic_notes"] == [
        "[audience, low] card 1: x"]
    assert {"silent_s", "crowded", "need_s", "voiceover", "issues", "envelope_s", "multi_speaker"} <= set(report)
    assert fields["status"] == "split"
    back = StoredPlan.load(fields["adam"])
    assert back is not None and back.plan().cards == stored_of("phone_call").cards


def test_an_approved_scene_is_refused_and_a_scene_not_planned_by_adam_has_no_stored_plan():
    stored = stored_of("phone_call")
    out = step.run({"scene": {**SCENE_ROW, "status": "approved"}, "lines": [], "stored": stored.data(), "fit": {}})
    assert out == {"refused": "an approved scene is never touched"}
    assert StoredPlan.load({}) is None and StoredPlan.load({"planner": "adam", "junk": 1}) is None


def test_the_same_plan_written_twice_gives_the_same_rows_apart_from_their_new_ids():
    first, second = written(), written()

    def plain(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{k: v for k, v in r.items() if k not in ("id", "shot_id")} for r in rows]

    assert plain(first["shots"]) == plain(second["shots"]) and plain(first["lines"]) == plain(second["lines"])
    assert first["shots"][0]["id"] != second["shots"][0]["id"]


def test_a_malformed_plan_says_so_instead_of_raising():
    assert "malformed" in step.run({"scene": SCENE_ROW, "lines": [], "stored": {"planner": "adam"}, "fit": {}})


@pytest.mark.parametrize("name", gold.names())
def test_every_gold_master_writes_a_shot_for_each_card_and_binds_each_of_its_lines(name: str):
    stored = stored_of(name)
    out = step.run({"scene": SCENE_ROW, "lines": line_rows(name), "stored": stored.data(),
                    "fit": fit_of(name, stored)})
    assert len(out["shots"]) == len(stored.cards)
    assert sum(1 for ln in out["lines"] if ln["shot_id"]) == len(line_rows(name))


def test_an_elaboration_a_person_removed_is_never_added_back_but_the_script_never_goes():
    stored = stored_of("phone_call")
    extra = next(m for m in stored.moments if m.tier == "elaboration")
    removed = [Removed.of(extra).model_dump()]
    again = Moment(id="m77", tier="elaboration", kind=extra.kind, serves=extra.serves, seen="the same thing, new id")
    script = next(m for m in stored.moments if m.tier == "script")
    out = step.run({"moments": [m.model_dump(mode="json") for m in [*stored.moments, again]], "removed": removed})
    assert extra.id in out["dropped"] and "m77" in out["dropped"] and script.id not in out["dropped"]
    assert logic.describe(Removed.of(extra)).startswith(extra.kind)
