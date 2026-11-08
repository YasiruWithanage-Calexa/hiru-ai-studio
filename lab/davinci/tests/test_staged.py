"""Offline tests of the staged runner (plan/2026-11-08d PLAN-B.md): no model, no network, no database.

Run from the repo root:  .venv/Scripts/python.exe -m pytest lab/davinci/tests -q
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from test_lab import walk  # the strict-schema walker of the orchestrator's tests

from cinematic import pack
from davinci import checks, money, orchestrator, rehearsal, run, schema, stages
from davinci.state import Bin


@pytest.fixture(scope="module")
def reading() -> pack.Reading:
    return rehearsal.reading()


def staged(tmp_path: Path, backend: Any = None, cfg: stages.Config | None = None, **meter_args: Any
           ) -> tuple[stages.Stages, stages.StagedOutcome, money.Meter, Any]:
    backend = backend or rehearsal.StagedRehearsal()
    meter = money.Meter(tmp_path / "pretend.csv", "test", **meter_args)
    runner = stages.Stages(rehearsal.reading(), backend, meter, tmp_path / "run", cfg)
    return runner, runner.run(), meter, backend


def loaded(first: bool = True) -> Bin:
    work = Bin()
    work.load(schema.PlanW.model_validate(rehearsal.staged_plan(first=first)))
    return work


def entry(**over: Any) -> schema.MenuW:
    base: dict[str, Any] = {"moment": 1, "role": "master", "setup": "A", "blocks": [0], "lines": [], "speaks": False, "over": "",
                            "size": "WIDE", "angle": "eye level", "lens": "35mm: place", "technique": "locked_off",
                            "why": "The place is a character.", "take_s": 6, "handle_in_s": 1.0, "handle_out_s": 1.0,
                            "priority": "must", "editor_note": ""}
    return schema.MenuW(**{**base, **over})


# ── the schema and the messages ──────────────────────────────────────────────────────────────────


def test_the_plan_schema_is_strict_and_holds_the_whole_answer() -> None:
    sch = schema.plan_schema()
    assert walk(sch) == []
    assert sch["title"] == "shot_plan" and set(sch["properties"]) == {"edit_plan", "clips", "looks"}
    assert set(sch["properties"]["looks"]["items"]["properties"]) == {"moment", "setting", "lighting", "people"}


def test_the_staged_plan_table_fits_its_schema() -> None:
    for first in (True, False):
        plan = schema.PlanW.model_validate(rehearsal.staged_plan(first=first))
        assert len(plan.looks) == len(plan.edit_plan.moments) == 8


def test_the_models_are_told_seconds_never_money(tmp_path: Path) -> None:
    _, _, _, backend = staged(tmp_path)
    assert backend.messages
    for text in backend.messages:
        assert not re.search(r"\$\d|dollar|spent|credit|\bcost", text, re.IGNORECASE)
    assert "at most 90 s of takes" in backend.messages[0] and "never a goal to fill" in backend.messages[0]


def test_the_repair_message_carries_the_first_message_the_answer_and_every_fault(tmp_path: Path) -> None:
    _, _, _, backend = staged(tmp_path)
    repair = next(m for m in backend.messages if "<faults>" in m and "<your_answer>" in m)
    assert repair.startswith(backend.messages[0].split("\n\nPlan this scene")[0])  # the first message, then
    assert re.search(r'"id":"c01"', repair)  # the ids are code's, so a fault can name its clip
    faults = repair.split("<faults>")[1].split("</faults>")[0]
    assert "Moment 3 has no must clip" in faults and "Block b4 has no must clip" in faults
    assert "L22" not in faults  # code mended it before the director saw the faults


# ── stage 1: plan, check, mend ───────────────────────────────────────────────────────────────────


def test_plan_checks_judge_no_design(reading: pack.Reading) -> None:
    work = loaded(first=False)
    assert checks.plan_checks(reading, work) == []  # a complete menu with no design yet is a clean PLAN
    assert {f.code for f in checks.check_all(reading, work)} == {"design"}  # and only the designs are missing


def test_mend_fills_a_missing_line_id_and_nothing_else(reading: pack.Reading) -> None:
    work = loaded(first=True)
    before = {c.id: c.model_dump() for c in work.clips}
    assert any("L22" in f.sentence for f in checks.plan_checks(reading, work))
    notes = checks.mend(reading, work)
    assert len(notes) == 1 and "L22" in notes[0]
    after = {c.id: c.model_dump() for c in work.clips}
    changed = [i for i in before if before[i] != after[i]]
    assert len(changed) == 1 and after[changed[0]]["lines"] == ["L22"]
    assert {k for k in before[changed[0]] if before[changed[0]][k] != after[changed[0]][k]} == {"lines"}
    assert not any("L22" in f.sentence for f in checks.plan_checks(reading, work))
    assert checks.mend(reading, work) == []  # a second pass finds nothing


def test_mend_never_deletes_a_clip_or_a_coverage_hole(reading: pack.Reading) -> None:
    work = loaded(first=True)
    ids = [c.id for c in work.clips]
    checks.mend(reading, work)
    assert [c.id for c in work.clips] == ids
    assert any("Moment 3 has no must clip" in f.sentence for f in checks.plan_checks(reading, work))  # judgement stays the director's


def test_mend_clamps_a_handle_and_rounds_a_take_up_only_inside_the_limit(reading: pack.Reading) -> None:
    work = Bin()
    work.add(entry(blocks=[4], take_s=4, handle_in_s=1.5, handle_out_s=1.5))  # 4 s cannot hold 1.5 + 1.5 + the action
    work.add(entry(moment=2, blocks=[3], handle_in_s=2.5))
    notes = checks.mend(reading, work)
    assert work.clips[0].take_s == 6 and work.clips[1].handle_in_s == 2.0
    assert any("rounded up to 6" in n for n in notes) and any("set to 2 s" in n for n in notes)
    full = Bin()
    full.add(entry(blocks=[4], take_s=4, handle_in_s=1.5, handle_out_s=1.5))
    for _ in range(14):
        full.add(entry(moment=2, setup="B", blocks=[], take_s=6))
    full.add(entry(moment=3, setup="C", blocks=[], take_s=4))  # 4 + 84 + 4 = 92 s: rounding the first clip to 6 would make 94
    checks.mend(reading, full)
    assert full.clips[0].take_s == 4  # not rounded: the bin would be longer than the limit


def test_a_line_overrun_is_reported_never_mended(reading: pack.Reading) -> None:
    work = Bin()
    clip = work.add(entry(moment=7, role="single", blocks=[16], lines=["L16"], take_s=4, handle_in_s=0.0, handle_out_s=0.0))
    assert checks.mend(reading, work) == [] and clip.take_s == 4


# ── the look sheet ───────────────────────────────────────────────────────────────────────────────


def test_the_look_sheet_overwrites_the_writers_words(reading: pack.Reading) -> None:
    work = loaded(first=False)
    clip = next(c for c in work.clips if c.moment == 5 and c.role == "single")
    clip.ir = rehearsal.design(clip.model_dump(), ["Kasun"])
    clip.ir["lighting"], clip.ir["setting"] = "Cold fluorescent light", "A studio"
    clip.ir["first_frame"]["lighting"], clip.ir["first_frame"]["setting"] = "Cold fluorescent light", "A studio"
    clip.ir["subjects"][0]["description"] = "Kasun in a red shirt"
    changed = checks.apply_looks(work)
    look = next(m for m in work.looks if m.moment == 5)
    assert changed == 5
    assert clip.ir["lighting"] == clip.ir["first_frame"]["lighting"] == look.lighting
    assert clip.ir["setting"] == clip.ir["first_frame"]["setting"] == look.setting
    assert clip.ir["subjects"][0]["description"] == look.people[0].description
    assert checks.apply_looks(work) == 0  # idempotent


def test_an_aerial_clip_keeps_its_own_setting_but_gets_the_peoples_looks(reading: pack.Reading) -> None:
    work = loaded(first=False)
    clip = work.clips[0]
    clip.technique, clip.role = "drone_establishing", "establishing"
    clip.ir = rehearsal.design(clip.model_dump(), ["Kasun"])
    clip.ir["setting"] = "From above: a wet grey city"
    clip.ir["subjects"][0]["description"] = "a small figure"
    checks.apply_looks(work)
    assert clip.ir["setting"] == "From above: a wet grey city"
    assert clip.ir["subjects"][0]["description"] == rehearsal.LOOKS["Kasun"]


def test_a_moment_without_a_look_is_a_fault_and_a_sheet_not_asked_for_is_not(reading: pack.Reading) -> None:
    work = loaded(first=False)
    work.looks = [m for m in work.looks if m.moment != 3]
    assert any(f.code == "looks" and "Moment 3" in f.sentence for f in checks.plan_checks(reading, work))
    work.looks = []  # the orchestrator never writes one: nothing is checked
    assert not [f for f in checks.check_all(reading, work) if f.code == "looks"]


# ── the staged run, end to end ───────────────────────────────────────────────────────────────────


def test_the_staged_rehearsal_finishes_with_nothing_blocking(tmp_path: Path) -> None:
    runner, out, meter, _ = staged(tmp_path)
    assert out.finished and not checks.blocking(out.faults) and out.detail == ""
    assert len(runner.work.clips) == 14 and all(c.ir is not None for c in runner.work.clips)
    assert sum(c.take_s for c in runner.work.clips) == 90
    assert out.editor_notes and "Masters" in out.editor_notes[0]
    assert [s["stage"] for s in out.stages] == ["plan", "repair", "design", "redesign"]
    assert sum(s["calls"] for s in out.stages) == meter.calls == 9
    assert sum(s["dollars"] for s in out.stages) == pytest.approx(meter.spent, abs=1e-3)


def test_each_stage_records_its_time_calls_and_dollars(tmp_path: Path) -> None:
    _, out, _, _ = staged(tmp_path)
    rows = [json.loads(line) for line in (tmp_path / "run" / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    done = [r["stage_done"] for r in rows if "stage_done" in r]
    assert [d["stage"] for d in done] == ["plan", "repair", "design", "redesign"]
    for d in done:
        assert {"start", "end", "seconds", "calls", "dollars", "detail"} <= set(d)
    assert done[0]["calls"] == 1 and done[1]["calls"] == 1 and done[2]["calls"] == 6 and done[3]["calls"] == 1
    assert "mend: 1 fix" in out.stages[0]["detail"] and "2 -> 0" in out.stages[1]["detail"]


def test_a_repair_is_kept_only_when_it_leaves_fewer_blocking_faults(tmp_path: Path) -> None:
    good = staged(tmp_path / "good")[0]
    same = staged(tmp_path / "same", rehearsal.StagedRehearsal(repair="same"))
    worse = staged(tmp_path / "worse", rehearsal.StagedRehearsal(repair="worse"))
    assert len(good.work.clips) == 14
    for runner, out, _, backend in (same, worse):
        assert len(runner.work.clips) == 13  # the first plan stays: neither repair left fewer faults
        assert out.stopped == "incomplete" and "marked incomplete" in out.detail
        assert [k for k, _ in backend.calls].count("repair") == 2  # two rounds, then it stops
        assert "NOT kept" in out.stages[1]["detail"]
        assert any("Moment 3" in f.sentence for f in out.faults)  # the fault is reported, not hidden
        assert all(c.ir is not None for c in runner.work.clips)  # the design stage still ran: the bin is complete but for the fault


def test_the_better_rule() -> None:
    f = checks._fault("coverage", "x", "director")
    r = checks._fault("clock", "y", "director", fix="report")
    assert checks.better([], [f]) and not checks.better([f], [f]) and not checks.better([f, f], [f])
    assert checks.better([r], [f, r])  # a report is not a blocking fault


def test_the_redesign_sends_only_the_failing_clips(tmp_path: Path) -> None:
    runner, out, _, backend = staged(tmp_path)
    designed_once = [i for kind, ids in backend.calls if kind == "design" for i in ids]
    redo = [ids for kind, ids in backend.calls if kind == "redesign"]
    assert sorted(designed_once) == sorted(c.id for c in runner.work.clips)  # every clip designed exactly once at stage 3
    assert redo == [["c11"]]  # one call, one clip: the one with the voice-only father in frame
    c11 = runner.work.by_id("c11")
    assert c11 is not None and c11.ir is not None and "Father" not in json.dumps(c11.ir)
    assert "round 1: 1 clip(s) sent (c11), 0 still failing" in out.stages[3]["detail"]
    message = next(m for m in backend.messages if "<faults>" in m and "<clips>" in m and "<your_answer>" not in m)
    assert "c11:" in message and "Father" in message.split("<faults>")[1]


def test_the_look_sheet_makes_the_angles_match_without_a_re_design(tmp_path: Path) -> None:
    runner, out, _, backend = staged(tmp_path)
    group = [c for c in runner.work.clips if c.moment == 5]
    assert len({c.ir["lighting"] for c in group if c.ir}) == 1 and len({c.ir["setting"] for c in group if c.ir}) == 1
    assert not [f for f in out.faults if f.code == "consistency"]
    redo = [ids for kind, ids in backend.calls if kind == "redesign"]
    assert len(redo) == 1  # the writer that wrote another light and another look was NOT sent back: code fixed it


def test_designs_go_out_in_parallel_batches_by_sequence(tmp_path: Path) -> None:
    runner, _, _, backend = staged(tmp_path)
    work = runner.work
    groups = stages.groups_of(list(work.clips), work, 3)
    assert work.edit is not None
    seq_of = {m.n: m.sequence for m in work.edit.moments}
    assert sorted(c.id for g in groups for c in g) == sorted(c.id for c in work.clips)
    assert all(1 <= len(g) <= 3 for g in groups)
    assert all(len({seq_of[c.moment] for c in g}) == 1 for g in groups)  # a batch never crosses two sequences
    sizes = [len(g) for g in groups if seq_of[g[0].moment] == "B"]
    assert sizes == [3, 2, 2]  # 7 clips: as even as it can be, not 3 + 3 + 1
    design_calls = [ids for kind, ids in backend.calls if kind == "design"]
    assert len(design_calls) == len(groups) == 6


def test_the_threads_and_the_batch_are_the_configs(tmp_path: Path) -> None:
    runner, _, _, backend = staged(tmp_path, cfg=stages.Config(batch=2))
    sizes = [len(ids) for kind, ids in backend.calls if kind == "design"]
    assert max(sizes) <= 2 and sum(sizes) == len(runner.work.clips)
    assert stages.Config().threads == 8 and stages.Config().batch == 3 and stages.Config().director_max_output == 32_000


def test_no_repair_call_when_the_plan_is_clean(tmp_path: Path) -> None:
    class Clean(rehearsal.StagedRehearsal):
        def structured(self, **kw: Any) -> Any:
            if kw["schema"]["title"] == "shot_plan":  # the very first answer is already the corrected plan
                self.calls.append(("plan", []))
                return rehearsal.Reply(id="p", text=json.dumps(rehearsal.staged_plan(first=False)),
                                       usage=money.Usage(12000, 0, 18000, 12000))
            return super().structured(**kw)

    _, out, _, backend = staged(tmp_path, Clean())
    assert out.finished and [k for k, _ in backend.calls].count("plan") == 1 and "repair" not in [k for k, _ in backend.calls]
    assert out.stages[1]["calls"] == 0 and "nothing to repair" in out.stages[1]["detail"]


# ── the money rules still hold ───────────────────────────────────────────────────────────────────


def test_a_staged_run_stops_at_its_cap(tmp_path: Path) -> None:
    _, out, meter, _ = staged(tmp_path, run_cap=0.10)
    assert out.stopped == "cap" and meter.spent >= 0.10
    assert meter.spent < 0.10 + 0.25  # the plan call (pretend $0.195) took it over; nothing more was sent


def test_the_lab_budget_refuses_a_staged_call_before_it_is_sent(tmp_path: Path) -> None:
    _, out, meter, backend = staged(tmp_path, lab_budget=0.01)
    assert out.stopped == "budget" and meter.calls == 0 and backend.calls == []


def test_a_group_of_designs_is_reserved_before_any_is_sent(tmp_path: Path) -> None:
    """A budget that holds the plan, the repair and one writer but not six: the design group is refused whole, nothing is half-sent."""
    runner, out, meter, backend = staged(tmp_path, lab_budget=0.6)
    assert out.stopped == "budget"
    assert [k for k, _ in backend.calls if k == "design"] == []  # none of the six was sent
    assert meter.reserved == pytest.approx(0, abs=1e-9)  # and every reservation was given back
    assert runner.work.clips and all(c.ir is None for c in runner.work.clips)


def test_a_failed_plan_call_is_entered_at_its_worst_case_and_ends_the_run(tmp_path: Path) -> None:
    class Down(rehearsal.StagedRehearsal):
        def structured(self, **kw: Any) -> Any:
            raise TimeoutError("down")

    _, out, meter, _ = staged(tmp_path, Down())
    assert out.stopped == "error" and "TimeoutError" in out.detail
    assert meter.calls == 1 and meter.spent > 0.3 and "failed at worst case" in meter.rows()[0]["status"]


def test_an_answer_that_does_not_fit_the_schema_ends_stage_one_with_a_reason(tmp_path: Path) -> None:
    class Garbage(rehearsal.StagedRehearsal):
        def structured(self, **kw: Any) -> Any:
            return rehearsal.Reply(id="g", text='{"edit_plan": 1}', usage=money.Usage(1000, 0, 1000, 0))

    runner, out, _, _ = staged(tmp_path, Garbage())
    assert out.stopped == "error" and "did not fit its schema" in out.detail and runner.work.clips == []


# ── the command ──────────────────────────────────────────────────────────────────────────────────


def test_staged_is_the_default_and_the_command_never_builds_a_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import cinematic.run as cinematic_run

    monkeypatch.setattr(cinematic_run, "client", lambda: (_ for _ in ()).throw(AssertionError("a client was built")))
    monkeypatch.setattr(run, "RUNS", tmp_path)
    assert run.main(["rehearse"]) == 0
    folder = tmp_path / "rehearsal-staged"
    html = (folder / "bin.html").read_text(encoding="utf-8")
    assert "REHEARSAL (staged)" in html and "<h2>Stages</h2>" in html and "redesign" in html and "1P-1" in html
    out = json.loads((folder / "outcome.json").read_text(encoding="utf-8"))
    assert out["stopped"] == "finished" and [s["stage"] for s in out["stages"]] == ["plan", "repair", "design", "redesign"]
    looks = json.loads((folder / "looks.json").read_text(encoding="utf-8"))
    assert len(looks) == 8 and (folder / "edit_plan.json").exists() and (folder / "bin.json").exists()
    assert not (tmp_path / "rehearsal").exists()  # the orchestrator's folder is not touched


def test_dry_prints_the_message_the_schema_and_the_worst_case_of_the_whole_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert run.main(["dry"]) == 0
    text = capsys.readouterr().out
    assert "stage 1 message" in text and "plan schema" in text and "WORST case of the whole run" in text
    assert "redesign" in text and "A paid run is allowed" in text


def test_the_worst_case_of_a_staged_run_is_inside_what_the_lab_has_left(reading: pack.Reading) -> None:
    rows = dict(stages.worst_case_run(reading, stages.Config(), money.worst_case))
    assert set(rows) == {"plan", "repair", "design", "redesign"}
    assert sum(rows.values()) < 3.27  # the budget left after runs 1 and 2


def test_the_orchestrator_is_unchanged_and_still_rehearses(tmp_path: Path) -> None:
    reading = rehearsal.reading()
    backend = rehearsal.Rehearsal()
    orch = orchestrator.Orchestrator(reading, backend, money.Meter(tmp_path / "l.csv", "r"), tmp_path / "run")
    backend.bind(orch)
    assert orch.run().finished and orchestrator.prompt("director") != orchestrator.prompt("director_plan")
