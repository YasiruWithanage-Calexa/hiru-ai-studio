"""Offline tests of the DaVinci lab (plan/2026-11-08d phase 0): no model, no network, no database.

Run from the repo root:  .venv/Scripts/python.exe -m pytest lab/davinci/tests -q
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from cinematic import pack
from davinci import checks, money, orchestrator, rehearsal, render, run, schema
from davinci.state import Bin

LAB = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def reading() -> pack.Reading:
    return rehearsal.reading()


def entry(**over: Any) -> schema.MenuW:
    base: dict[str, Any] = {"moment": 1, "role": "master", "setup": "A", "blocks": [0], "lines": [], "speaks": False, "over": "",
                            "size": "WIDE", "angle": "eye level", "lens": "35mm: place", "technique": "locked_off",
                            "why": "The place is a character.", "take_s": 6, "handle_in_s": 1.0, "handle_out_s": 1.0,
                            "priority": "must", "editor_note": ""}
    return schema.MenuW(**{**base, **over})


def rehearsed(tmp_path: Path, **meter_args: Any) -> tuple[orchestrator.Orchestrator, orchestrator.Outcome, money.Meter]:
    reading = rehearsal.reading()
    meter = money.Meter(tmp_path / "pretend.csv", "test", **meter_args)
    backend = rehearsal.Rehearsal()
    orch = orchestrator.Orchestrator(reading, backend, meter, tmp_path / "run")
    backend.bind(orch)
    return orch, orch.run(), meter


def clean_bin(reading: pack.Reading, tmp_path: Path) -> Bin:
    orch, out, _ = rehearsed(tmp_path)
    assert out.finished
    return orch.work


# ── the rehearsal: the real loop with no model ───────────────────────────────────────────────────


def test_rehearsal_finishes_with_nothing_blocking(tmp_path: Path) -> None:
    orch, out, meter = rehearsed(tmp_path)
    assert out.finished and not checks.blocking(out.faults)
    assert 12 <= len(orch.work.clips) <= 25 and all(c.ir is not None for c in orch.work.clips)
    assert meter.spent < money.RUN_CAP_USD and meter.calls > 10


def test_finish_refuses_until_the_checks_pass(tmp_path: Path) -> None:
    _, _, _ = rehearsed(tmp_path)
    rows = [json.loads(line) for line in (tmp_path / "run" / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    finishes = [r for r in rows if r.get("tool") == "finish"]
    assert finishes[0]["result"].startswith("Refused") and finishes[-1]["result"].startswith("Finished")


def test_a_repair_resends_only_the_clip_that_failed(tmp_path: Path) -> None:
    _, _, _ = rehearsed(tmp_path)
    rows = [json.loads(line) for line in (tmp_path / "run" / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    writes = [json.loads(r["args"]) for r in rows if r.get("tool") == "write_clips"]
    assert len(writes) == 2 and writes[1]["clip_ids"] == ["c07"]
    checked = [r["result"] for r in rows if r.get("tool") == "check"]
    assert "consistency" in checked[0] and "No faults" in checked[1]


def test_no_tool_result_shows_the_model_a_budget(tmp_path: Path) -> None:
    _, _, _ = rehearsed(tmp_path)
    text = (tmp_path / "run" / "trace.jsonl").read_text(encoding="utf-8")
    results = " ".join(json.loads(line).get("result", "") for line in text.splitlines())
    assert not re.search(r"\$\d|budget|cap\b|spent", results, re.IGNORECASE)


def test_the_director_plans_one_clip_itself_and_slates_never_repeat(tmp_path: Path) -> None:
    orch, _, _ = rehearsed(tmp_path)
    slates = [c.slate for c in orch.work.clips]
    assert len(set(slates)) == len(slates) and orch.work.clips[-1].technique == "tilt_reveal"
    assert re.fullmatch(r"1[A-Z]-\d+", slates[0])


def test_rehearse_command_never_builds_a_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import cinematic.run as cinematic_run

    monkeypatch.setattr(cinematic_run, "client", lambda: (_ for _ in ()).throw(AssertionError("a client was built")))
    monkeypatch.setattr(run, "RUNS", tmp_path)
    assert run.main(["rehearse", "--mode", "orchestrator"]) == 0
    html = (tmp_path / "rehearsal" / "bin.html").read_text(encoding="utf-8")
    assert "REHEARSAL: no model wrote this" in html and "Moment 5" in html and "1P-1" in html


# ── the money rules ──────────────────────────────────────────────────────────────────────────────


def test_a_run_stops_at_its_cap_and_may_pass_it_by_one_call(tmp_path: Path) -> None:
    _, out, meter = rehearsed(tmp_path, run_cap=0.10)
    assert out.stopped == "cap" and meter.spent >= 0.10
    assert meter.spent < 0.10 + 0.1  # at most the last call (or parallel group) over


def test_the_lab_budget_refuses_a_call_before_it_is_sent(tmp_path: Path) -> None:
    _, out, meter = rehearsed(tmp_path, lab_budget=0.01)
    assert out.stopped == "budget" and meter.calls == 0 and meter.ledger_total() == 0


def test_a_failed_call_is_entered_at_its_worst_case(tmp_path: Path) -> None:
    meter = money.Meter(tmp_path / "l.csv", "r")
    worst = meter.guard("gpt-5", 10_000, 16_000)
    meter.fail("director", "gpt-5", "medium", worst, "Timeout")
    assert meter.spent == pytest.approx(worst) and meter.reserved == 0 and meter.ledger_total() == pytest.approx(worst)


def test_a_model_without_a_price_is_refused(tmp_path: Path) -> None:
    with pytest.raises(money.LabError, match="no price"):
        money.Meter(tmp_path / "l.csv", "r").guard("gpt-9-unknown", 1000, 1000)


def test_parallel_reservations_count_against_the_budget(tmp_path: Path) -> None:
    meter = money.Meter(tmp_path / "l.csv", "r", lab_budget=0.30)
    first = meter.guard("gpt-5-mini", 5000, 20_000)  # about $0.04 worst case
    meter.guard("gpt-5-mini", 5000, 20_000)
    assert meter.reserved == pytest.approx(2 * first)
    with pytest.raises(money.LabError, match="in flight"):
        for _ in range(10):
            meter.guard("gpt-5-mini", 5000, 20_000)
    meter.release(first)
    assert meter.reserved < 10 * first


def test_the_lab_ledger_survives_between_runs(tmp_path: Path) -> None:
    a = money.Meter(tmp_path / "l.csv", "one")
    a.charge("director", "gpt-5", "medium", money.Usage(10_000, 0, 2_000, 1_000), a.guard("gpt-5", 10_000, 16_000))
    b = money.Meter(tmp_path / "l.csv", "two")
    assert b.ledger_total() == pytest.approx(a.spent) and b.spent == 0


# ── the schemas are strict ───────────────────────────────────────────────────────────────────────


def walk(node: Any, path: str = "") -> list[str]:
    bad = []
    if isinstance(node, dict):
        if node.get("type") == "object":
            props = node.get("properties")
            if node.get("additionalProperties") is not False:
                bad.append(f"{path}: additionalProperties is not false")
            if props is not None and sorted(node.get("required") or []) != sorted(props):
                bad.append(f"{path}: not every property is required")
        for key in ("default", "$ref", "anyOf", "allOf", "oneOf"):
            if key in node and key != "anyOf":
                bad.append(f"{path}: {key} is not allowed in strict mode")
        for k, v in node.items():
            bad += walk(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            bad += walk(v, f"{path}[{i}]")
    return bad


def test_every_schema_and_tool_is_strict() -> None:
    for name, sch in (("edit", schema.edit_schema()), ("menu", schema.menu_schema()), ("designs", schema.ir_list_schema())):
        assert walk(sch) == [], name
    for spec in orchestrator.tool_specs():
        assert spec["strict"] and walk(spec["parameters"]) == [], spec["name"]


def test_the_design_is_the_clip_schemas_in_every_clip() -> None:
    ir = schema.ir_list_schema()["properties"]["designs"]["items"]["properties"]["ir"]
    assert "cinematography" in ir["properties"] and "first_frame" in ir["properties"]


def test_the_technique_menu_has_no_refused_technique() -> None:
    assert not [t for t in schema.TECHNIQUES if re.search(r"dolly_zoom|diopter|speed_ramp|freeze|punch|split_screen", t)]
    assert set(schema.TECHNIQUES) == set(schema.Technique.__args__)  # type: ignore[attr-defined]


def test_the_prompts_tell_no_story() -> None:
    for name in ("director", "coverage", "clip_writer", "director_plan", "director_repair", "clip_writer_staged"):
        text = orchestrator.prompt(name)
        assert not re.search(r"Kasun|Anudi|Colombo|umbrella|three-wheeler|\btea\b|marriage", text, re.IGNORECASE), name


# ── the checks ───────────────────────────────────────────────────────────────────────────────────


def test_a_complete_bin_has_no_fault(reading: pack.Reading, tmp_path: Path) -> None:
    assert checks.check_all(reading, clean_bin(reading, tmp_path)) == []


def faults_after(reading: pack.Reading, work: Bin) -> dict[str, list[checks.Fault]]:
    out: dict[str, list[checks.Fault]] = {}
    for f in checks.check_all(reading, work):
        out.setdefault(f.code, []).append(f)
    return out


def test_a_block_with_no_must_clip_is_found(reading: pack.Reading, tmp_path: Path) -> None:
    work = clean_bin(reading, tmp_path)
    for c in list(work.clips):
        if c.moment == 3:
            work.remove(c.id)
    found = faults_after(reading, work)["coverage"]
    assert any("b4" in f.sentence for f in found) and any("Moment 3" in f.sentence for f in found)


def test_a_heard_line_may_not_be_performed(reading: pack.Reading, tmp_path: Path) -> None:
    work = clean_bin(reading, tmp_path)
    narrator = next(c for c in work.clips if "L22" in c.lines)
    narrator.speaks = True
    assert any("L22" in f.sentence and "heard and not seen" in f.sentence for f in faults_after(reading, work)["coverage"])


def test_a_seen_line_needs_a_performer(reading: pack.Reading, tmp_path: Path) -> None:
    work = clean_bin(reading, tmp_path)
    for c in work.clips:
        c.speaks = False
    found = faults_after(reading, work)["coverage"]
    assert any("L7" in f.sentence and "performed by no must clip" in f.sentence for f in found)


def test_a_transition_needs_both_halves(reading: pack.Reading, tmp_path: Path) -> None:
    work = Bin()
    work.add(entry(moment=4, role="transition_out", technique="whip_out", blocks=[6], take_s=6))
    work.add(entry(moment=5, role="transition_in", technique="whip_in", blocks=[], take_s=4))
    assert not [f for f in checks.coverage(reading.scene, work) if "both halves" in f.sentence]
    work.remove("c02")
    assert any("both halves" in f.sentence for f in checks.coverage(reading.scene, work))


def test_the_bin_stays_within_the_given_length_plus_half(reading: pack.Reading, tmp_path: Path) -> None:
    assert checks.limit_s(reading) == 90
    work = clean_bin(reading, tmp_path)
    assert sum(c.take_s for c in work.clips) <= 90 and checks.length(reading, work) == []
    work.add(entry(moment=1, role="atmosphere", blocks=[], priority="nice", take_s=4))  # 94 s
    found = checks.length(reading, work)
    assert found and found[0].fix == "repair" and found[0].owner == "director" and "90 s" in found[0].sentence
    assert found[0] in checks.blocking(checks.check_all(reading, work))  # finish refuses a bin that is too long


def test_no_length_given_means_no_limit(reading: pack.Reading) -> None:
    no_time = pack.Reading(raw={**reading.raw, "time": {}}, scene=reading.scene)
    work = Bin()
    work.add(entry(take_s=8))
    assert checks.limit_s(no_time) == 0 and checks.length(no_time, work) == []


def test_the_models_are_told_the_limit_in_seconds_not_money(reading: pack.Reading, tmp_path: Path) -> None:
    orch = orchestrator.Orchestrator(reading, rehearsal.Rehearsal(), money.Meter(tmp_path / "l.csv", "r"), tmp_path / "run")
    note = orch.length_note()
    assert "at most 90 s" in note and "90 s are left" in note and "$" not in note
    orch.work.add(entry(take_s=8))
    assert "82 s are left" in orch.length_note()


def test_a_long_line_is_reported_and_never_trimmed(reading: pack.Reading) -> None:
    work = Bin()
    clip = work.add(entry(moment=7, role="single", blocks=[16], lines=["L16"], take_s=4, handle_in_s=0.0, handle_out_s=0.0))
    found = checks.clock(reading.scene, work)
    assert found and found[0].fix == "report" and clip.id in found[0].clips and "never trimmed" in found[0].sentence
    assert not checks.blocking(found)  # reported to the person; it does not stop `finish`


def test_handles_that_do_not_fit_the_take_are_a_fault(reading: pack.Reading) -> None:
    work = Bin()
    work.add(entry(blocks=[4], take_s=4, handle_in_s=1.5, handle_out_s=1.5))
    found = checks.clock(reading.scene, work)
    assert found and found[0].fix == "repair" and found[0].owner == "director"
    work2 = Bin()
    work2.add(entry(blocks=[4], handle_in_s=2.5))
    assert "handle in is 2.5" in checks.clock(reading.scene, work2)[0].sentence


@pytest.mark.parametrize("words", ["a dolly zoom onto her face", "split diopter on the glass", "a speed ramp as he runs",
                                   "a freeze frame on the phone"])
def test_what_veo_cannot_do_is_refused(words: str) -> None:
    work = Bin()
    work.add(entry(why=f"The story needs {words}."))
    found = checks.feasibility(work)
    assert found and found[0].fix == "repair" and found[0].owner == "director"


def test_slow_motion_has_no_dialogue_and_the_language_limits_the_menu() -> None:
    work = Bin()
    work.add(entry(technique="slow_motion", blocks=[7], lines=["L7"], speaks=True))
    assert any("no dialogue" in f.sentence for f in checks.feasibility(work))
    assert any("visual language" in f.sentence for f in checks.feasibility(work, allowed=("locked_off",)))


def test_a_clip_with_no_story_reason_is_a_fault() -> None:
    work = Bin()
    work.add(entry(why="  "))
    assert any("no story reason" in f.sentence for f in checks.feasibility(work))


def test_a_voice_only_person_is_never_in_frame(reading: pack.Reading, tmp_path: Path) -> None:
    work = clean_bin(reading, tmp_path)
    clip = work.clips[5]
    assert clip.ir is not None
    clip.ir["subjects"] = [*clip.ir["subjects"], {"id": "C03", "description": "Father, polo shirt", "action": "waits", "position": "left"}]
    assert any("Father" in f.sentence for f in faults_after(reading, work)["design"])


def test_nobody_speaks_in_a_clip_that_performs_no_line(reading: pack.Reading, tmp_path: Path) -> None:
    work = clean_bin(reading, tmp_path)
    clip = next(c for c in work.clips if not c.speaks and c.ir)
    assert clip.ir is not None
    clip.ir["beats"][1]["action"] = "Kasun says hello to the customer"
    assert any("Veo invents the speech" in f.sentence for f in faults_after(reading, work)["design"])


def test_the_angles_of_a_moment_must_match_word_for_word(reading: pack.Reading, tmp_path: Path) -> None:
    work = clean_bin(reading, tmp_path)
    group = [c for c in work.clips if c.moment == 5 and c.ir]
    group[1].ir["subjects"][0]["description"] = "Kasun in a red shirt"  # type: ignore[index]
    found = faults_after(reading, work)["consistency"]
    assert found and found[0].owner == "clip_writer"


def test_a_clip_with_no_design_blocks_finish(reading: pack.Reading) -> None:
    work = Bin()
    work.add(entry())
    assert any(f.code == "design" and f.owner == "clip_writer" for f in checks.check_all(reading, work))


def test_the_edit_plan_covers_every_block_once(reading: pack.Reading, tmp_path: Path) -> None:
    work = clean_bin(reading, tmp_path)
    assert work.edit is not None
    work.edit.moments[0].blocks = [b for b in work.edit.moments[0].blocks if b != 1]
    work.edit.moments[1].blocks = [*work.edit.moments[1].blocks, 4]
    sentences = [f.sentence for f in checks.edit_plan(reading.scene, work)]
    assert any("b1 is in no moment" in s for s in sentences) and any("b4 is in moments" in s for s in sentences)


def test_tools_teach_when_called_wrongly(reading: pack.Reading, tmp_path: Path) -> None:
    orch = orchestrator.Orchestrator(reading, rehearsal.Rehearsal(), money.Meter(tmp_path / "l.csv", "r"), tmp_path / "run")
    assert "no tool nope" in orch.tool("nope", "{}")
    assert "not valid JSON" in orch.tool("check", "{")
    assert "Write the edit plan first" in orch.tool("plan_coverage", json.dumps({"moments": [1], "brief": ""}))
    assert "do not fit" in orch.tool("add_clips", json.dumps({"clips": [{"moment": 1}]}))


# ── the page and the small part for the post team ────────────────────────────────────────────────


def test_the_page_shows_the_cut_the_bin_and_jonathan(reading: pack.Reading, tmp_path: Path) -> None:
    orch, out, _ = rehearsed(tmp_path)
    jon = run.jonathan_plan("")
    html = render.build(reading, orch.work, out.faults, out.stopped, "", "source note", jon)
    assert "The intended cut" in html and "The shoot bin" in html and "Editor notes" in html
    assert "1P-1" in html and "performs the line" in html and "plays silent under the chosen audio" in html
    if jon:
        assert "Jonathan" in html


def test_the_sample_for_the_post_team(tmp_path: Path) -> None:
    orch, _, _ = rehearsed(tmp_path)
    clips = [c.model_dump() for c in orch.work.clips]
    sample = run.pick_sample(clips)
    assert len({c["size"] for c in sample["angles"]}) == 3 and {c["moment"] for c in sample["angles"]} == {5}
    assert sample["transition"] == [] and sample["broll"] == []  # the length limit left no room for them: said so, not invented
    extra = [{**clips[0], "id": "x1", "role": "transition_out", "technique": "whip_out"},
             {**clips[0], "id": "x2", "role": "transition_in", "technique": "whip_in"},
             {**clips[0], "id": "x3", "role": "establishing", "technique": "drone_establishing"}]
    sample = run.pick_sample([*clips, *extra])
    assert [c["role"] for c in sample["transition"]] == ["transition_out", "transition_in"]
    assert sample["broll"] and sample["broll"][0]["technique"].startswith("drone")


# ── a repair can never open a coverage hole ──────────────────────────────────────────────────────


def test_removing_the_last_must_clip_of_a_block_is_refused(tmp_path: Path) -> None:
    orch, _, _ = rehearsed(tmp_path)
    first = orch.work.clips[1]  # the thought (L3): the only must clip of block 3
    before = [c.id for c in orch.work.clips]
    result = orch.tool("remove_clips", json.dumps({"clip_ids": [first.id]}))
    assert "was not removed" in result and "replace_clip" in result
    assert [c.id for c in orch.work.clips] == before and not checks.coverage(orch.reading.scene, orch.work)


def test_no_removal_ever_leaves_the_coverage_worse(tmp_path: Path) -> None:
    """Whatever the director removes, the bin either keeps its coverage or the removal is refused."""
    orch, _, _ = rehearsed(tmp_path)
    refused = allowed = 0
    for clip in list(orch.work.clips):
        result = orch.tool("remove_clips", json.dumps({"clip_ids": [clip.id]}))
        refused += "was not removed" in result
        allowed += result.startswith(f"Removed {clip.id}")
        assert not checks.coverage(orch.reading.scene, orch.work), (clip.id, result)
    assert refused > 5 and allowed >= 1  # most clips are the only cover of something; a spare (the extra angles) can go


def test_replace_clip_keeps_the_id_and_a_must_status(tmp_path: Path) -> None:
    orch, _, _ = rehearsed(tmp_path)
    old = orch.work.clips[2]
    assert old.priority == "must" and old.ir is not None
    new_plan = old.model_dump(include=set(schema.MenuW.model_fields)) | {"priority": "nice", "technique": "dolly_in", "take_s": 8}
    result = orch.tool("replace_clip", json.dumps({"clip_id": old.id, "clip": new_plan}))
    new = orch.work.by_id(old.id)
    assert new is not None and "no design yet" in result
    assert new.priority == "must" and new.ir is None and new.technique == "dolly_in" and new.slate == old.slate
    assert [c.id for c in orch.work.clips].count(old.id) == 1
    assert "There is no clip" in orch.tool("replace_clip", json.dumps({"clip_id": "c99", "clip": new_plan}))


def test_the_clip_writers_are_given_the_voice_only_people(tmp_path: Path) -> None:
    orch, _, _ = rehearsed(tmp_path)
    note = orch.voice_only()
    assert "<voice_only>" in note and "Father" in note and "Narrator" not in note
    assert "never in `subjects`" in orchestrator.prompt("clip_writer") and "<voice_only>" in orchestrator.prompt("clip_writer")
