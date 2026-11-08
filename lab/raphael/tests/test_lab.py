"""Offline tests of the Raphael lab (plan/2026-11-08e phase 0a): no model, no network, no database.

Run from the repo root:  .venv/Scripts/python.exe -m pytest lab/raphael/tests -q
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from cinematic import pack
from davinci import checks, money
from davinci import schema as davinci_schema
from davinci.brain import Call, Reply
from davinci.money import Usage
from davinci.rehearsal import MENU
from raphael import agent, rehearsal, run, schema


@pytest.fixture(scope="module")
def reading() -> pack.Reading:
    return rehearsal.reading()


def rehearsed(tmp_path: Path, **meter_args: Any) -> tuple[agent.Raphael, agent.Outcome, money.Meter]:
    meter = money.Meter(tmp_path / "pretend.csv", "test", **meter_args)
    backend = rehearsal.Rehearsal()
    raph = agent.Raphael(rehearsal.reading(), backend, meter, tmp_path / "run")
    backend.bind(raph)
    return raph, raph.run(), meter


def trace(tmp_path: Path) -> list[dict[str, Any]]:
    text = (tmp_path / "run" / "trace.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


class Scripted:
    """A backend that sends a fixed list of (tool, args) turns, then idles."""

    def __init__(self, turns: list[tuple[str, dict[str, Any]]]) -> None:
        self.turns, self.i = turns, 0

    def step(self, **_: Any) -> Reply:
        if self.i >= len(self.turns):
            return Reply(id="idle", text="", usage=Usage(1000, 0, 10, 0))
        name, args = self.turns[self.i]
        self.i += 1
        return Reply(id=f"r{self.i}", calls=[Call(id=f"c{self.i}", name=name, args=json.dumps(args))],
                     usage=Usage(1000, 0, 100, 0))

    def structured(self, **_: Any) -> Reply:
        raise AssertionError("no worker")


def scripted(tmp_path: Path, turns: list[tuple[str, dict[str, Any]]], **cfg: Any) -> tuple[agent.Raphael, agent.Outcome]:
    raph = agent.Raphael(rehearsal.reading(), Scripted(turns), money.Meter(tmp_path / "p.csv", "t"), tmp_path / "run",
                         agent.Config(**cfg))
    return raph, raph.run()


def every_clip() -> dict[str, Any]:
    return {"clips": [rehearsal.complete(r) for r in MENU]}


# ── the rehearsal: the real loop with no model ───────────────────────────────────────────────────


def test_rehearsal_finishes_within_the_turn_cap_with_nothing_blocking(tmp_path: Path) -> None:
    raph, out, meter = rehearsed(tmp_path)
    assert out.finished and not checks.blocking(out.faults)
    assert out.turns <= agent.Config().max_turns == 20
    assert all(c.ir is not None and c.sound is not None for c in raph.work.clips)
    assert meter.calls == out.turns and meter.spent < money.RUN_CAP_USD


def test_the_rehearsal_has_a_refused_finish_one_batch_repair_and_an_accepted_finish(tmp_path: Path) -> None:
    rehearsed(tmp_path)
    rows = [r for r in trace(tmp_path) if "tool" in r]
    finishes = [r for r in rows if r["tool"] == "finish"]
    assert finishes[0]["result"].startswith("Refused") and finishes[-1]["result"].startswith("Finished")
    after = rows[rows.index(finishes[0]) + 1]
    assert after["tool"] == "put_clips"
    fixed = [c["id"] for c in json.loads(after["args"] if after["args"].endswith("}") else "{}").get("clips", [])] or \
        re.findall(r"c\d\d", after["result"].split("\n")[0])
    assert len(fixed) == 2  # both faults repaired in ONE call
    assert "Nothing blocks" in after["result"]


def test_raphael_asks_no_other_model(tmp_path: Path) -> None:
    _, out, _ = rehearsed(tmp_path)  # Rehearsal.structured raises: the run would fail if a worker were called
    rows = trace(tmp_path)
    assert out.finished and {r["slot"] for r in rows if "slot" in r} == {"raphael"}


def test_every_write_returns_the_report_and_there_is_no_check_tool(tmp_path: Path) -> None:
    rehearsed(tmp_path)
    for r in trace(tmp_path):
        if r.get("tool") in ("write_edit_plan", "put_clips", "remove_clips"):
            assert "Report:" in r["result"] and "target 60 s, cap 90 s" in r["result"]
    assert [s["name"] for s in agent.tool_specs()] == list(agent.TOOLS)
    assert "check" not in agent.TOOLS


def test_no_tool_result_shows_the_model_money(tmp_path: Path) -> None:
    rehearsed(tmp_path)
    results = " ".join(r.get("result", "") for r in trace(tmp_path))
    assert not re.search(r"\$\d|budget|dollar|spent|cost", results, re.IGNORECASE)
    raph = agent.Raphael(rehearsal.reading(), rehearsal.Rehearsal(), money.Meter(tmp_path / "x.csv", "x"), tmp_path / "x")
    assert not re.search(r"\$\d|budget|dollar|cost", raph.system + agent.length_block(raph.reading), re.IGNORECASE)


def test_slates_never_repeat_and_ids_are_code_given(tmp_path: Path) -> None:
    raph, _, _ = rehearsed(tmp_path)
    slates = [c.slate for c in raph.work.clips]
    assert len(set(slates)) == len(slates) and re.fullmatch(r"1[A-Z]-\d+", slates[0])
    assert [c.id for c in raph.work.clips] == [f"c{i:02d}" for i in range(1, len(raph.work.clips) + 1)]


def test_rehearse_command_never_builds_a_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import cinematic.run as cinematic_run

    monkeypatch.setattr(cinematic_run, "client", lambda: (_ for _ in ()).throw(AssertionError("a client was built")))
    monkeypatch.setattr(run, "RUNS", tmp_path)
    assert run.main(["rehearse"]) == 0
    html = (tmp_path / "rehearsal" / "bin.html").read_text(encoding="utf-8")
    assert "Raphael bin" in html and "REHEARSAL: no model wrote this" in html and "target of 60 s and a cap of 90 s" in html
    assert "<th>Raphael</th>" in html and "INCOMPLETE" not in html


# ── put_clips ────────────────────────────────────────────────────────────────────────────────────


def test_put_clips_adds_many_clips_in_one_call_each_complete(tmp_path: Path) -> None:
    from davinci.rehearsal import edit_plan

    raph, out = scripted(tmp_path, [("write_edit_plan", edit_plan()), ("put_clips", every_clip()),
                                    ("finish", {"editor_notes": ["n"]})])
    assert out.finished and out.turns == 3 and len(raph.work.clips) == len(MENU)


def test_put_clips_replaces_by_id_keeping_id_slate_and_must(tmp_path: Path) -> None:
    from davinci.rehearsal import edit_plan

    first = every_clip()
    lowered = {**rehearsal.complete(MENU[0], clip_id="c01"), "priority": "nice", "why": "a new reason"}
    raph, _ = scripted(tmp_path, [("write_edit_plan", edit_plan()), ("put_clips", first), ("put_clips", {"clips": [lowered]})])
    c = raph.work.by_id("c01")
    assert c is not None and c.slate == "1B-1" and c.priority == "must" and c.why == "a new reason" and c.ir is not None
    assert len(raph.work.clips) == len(MENU)


def test_put_clips_names_an_unknown_id_and_changes_nothing_for_it(tmp_path: Path) -> None:
    from davinci.rehearsal import edit_plan

    raph, _ = scripted(tmp_path, [("write_edit_plan", edit_plan()),
                                  ("put_clips", {"clips": [rehearsal.complete(MENU[0], clip_id="c99")]})])
    assert not raph.work.clips
    assert "c99 is not in the bin" in next(r for r in trace(tmp_path) if r.get("tool") == "put_clips")["result"]


def test_put_clips_before_the_edit_plan_is_refused(tmp_path: Path) -> None:
    raph, _ = scripted(tmp_path, [("put_clips", every_clip())])
    assert not raph.work.clips


def test_a_call_that_does_not_fit_the_schema_changes_nothing(tmp_path: Path) -> None:
    from davinci.rehearsal import edit_plan

    bad = every_clip()
    bad["clips"][3]["take_s"] = 5  # Veo makes 4, 6 or 8 s
    raph, _ = scripted(tmp_path, [("write_edit_plan", edit_plan()), ("put_clips", bad)])
    assert not raph.work.clips
    assert "Nothing was changed" in next(r for r in trace(tmp_path) if r.get("tool") == "put_clips")["result"]


def test_a_repeated_failed_fix_is_marked_and_an_unbuilt_hole_is_not(tmp_path: Path) -> None:
    from davinci.rehearsal import edit_plan

    broken = rehearsal.complete(MENU[5], broken=True)  # moment 5's Q single, another light
    bin_ = {"clips": [rehearsal.complete(r) if i != 5 else broken for i, r in enumerate(MENU)]}
    same = {**rehearsal.complete(MENU[5], broken=True), "id": "c06"}
    scripted(tmp_path, [("write_edit_plan", edit_plan()), ("put_clips", {"clips": bin_["clips"][:3]}),
                        ("put_clips", {"clips": bin_["clips"][3:]}), ("put_clips", {"clips": [same]})])
    puts = [r["result"] for r in trace(tmp_path) if r.get("tool") == "put_clips"]
    assert "STILL FAILING" not in puts[0] and "STILL FAILING" not in puts[1]
    assert "consistency [c06]" in puts[2] and "STILL FAILING" in puts[2]


def test_remove_clips_refuses_to_open_a_coverage_hole(tmp_path: Path) -> None:
    from davinci.rehearsal import edit_plan

    raph, _ = scripted(tmp_path, [("write_edit_plan", edit_plan()), ("put_clips", every_clip()),
                                  ("remove_clips", {"clip_ids": ["c01", "c06"]})])
    assert raph.work.by_id("c01") is not None and raph.work.by_id("c06") is None  # c01 is moment 1's must; c06 a should
    result = next(r for r in trace(tmp_path) if r.get("tool") == "remove_clips")["result"]
    assert "c01 was not removed" in result and "Report:" in result


# ── length: the target is the given length, 1.5x is a hard cap ───────────────────────────────────


def test_finish_refuses_a_bin_over_the_cap(tmp_path: Path) -> None:
    from davinci.rehearsal import edit_plan

    extra = {**rehearsal.complete(MENU[0]), "role": "atmosphere", "priority": "nice", "blocks": [], "take_s": 8}
    raph, out = scripted(tmp_path, [("write_edit_plan", edit_plan()), ("put_clips", every_clip()),
                                    ("put_clips", {"clips": [extra]}), ("finish", {"editor_notes": []})])
    assert not out.finished and raph.work.counts()["take_s"] > checks.limit_s(raph.reading)
    finish = next(r for r in trace(tmp_path) if r.get("tool") == "finish")["result"]
    assert finish.startswith("Refused") and "length" in finish


def test_the_opening_names_the_target_cap_and_voice_only_people(reading: pack.Reading, tmp_path: Path) -> None:
    raph = agent.Raphael(reading, rehearsal.Rehearsal(), money.Meter(tmp_path / "x.csv", "x"), tmp_path / "x")
    assert "TARGET: a bin of about 60 s" in raph.opening and "CAP: 90 s" in raph.opening
    assert "<voice_only>\nFather: heard and never seen" in raph.opening
    assert "allowed, not expected" in raph.opening and "<script>" in raph.opening


def test_no_length_given_means_no_length_block(reading: pack.Reading) -> None:
    bare = pack.Reading(raw={**reading.raw, "time": {}}, scene=reading.scene) if hasattr(pack.Reading, "__dataclass_fields__") \
        else None
    if bare is None:
        pytest.skip("Reading is not a dataclass")
    assert agent.length_block(bare) == ""


# ── the turn cap, the money rules ────────────────────────────────────────────────────────────────


def test_the_turn_cap_stops_the_run_and_saves_it_marked_incomplete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from davinci.rehearsal import edit_plan

    raph, out = scripted(tmp_path, [("write_edit_plan", edit_plan())] + [("read_bin", {"moment": 0})] * 30, max_turns=4)
    assert out.stopped == "turns" and out.turns == 4
    run.write_result(tmp_path / "out", raph.reading, raph, out, raph.meter, "test", None)
    saved = json.loads((tmp_path / "out" / "outcome.json").read_text(encoding="utf-8"))
    assert saved["complete"] is False and saved["stopped"] == "turns"
    assert "INCOMPLETE" in (tmp_path / "out" / "bin.html").read_text(encoding="utf-8")


def test_a_run_stops_at_its_cap(tmp_path: Path) -> None:
    _, out, meter = rehearsed(tmp_path, run_cap=0.20)
    assert out.stopped == "cap" and meter.spent >= 0.20


def test_the_lab_budget_refuses_a_call_before_it_is_sent(tmp_path: Path) -> None:
    _, out, meter = rehearsed(tmp_path, lab_budget=0.01)
    assert out.stopped == "budget" and meter.calls == 0 and meter.ledger_total() == 0


def test_a_failed_call_is_entered_at_its_worst_case(tmp_path: Path) -> None:
    class Broken(Scripted):
        def step(self, **_: Any) -> Reply:
            raise TimeoutError("slow")

    meter = money.Meter(tmp_path / "l.csv", "r")
    raph = agent.Raphael(rehearsal.reading(), Broken([]), meter, tmp_path / "run")
    out = raph.run()
    assert out.stopped == "error" and meter.calls == 1 and meter.spent > 0
    assert meter.ledger_total() == pytest.approx(meter.spent, abs=1e-4)


def test_raphael_has_its_own_ledger() -> None:
    assert run.LEDGER.parent.parent.name == "raphael" and run.LEDGER != Path(money.__file__).parent / "runs" / "ledger.csv"


def test_paid_needs_yes_then_a_hypothesis_then_stops_after_three_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run, "LEDGER", tmp_path / "ledger.csv")
    assert run.main(["paid"]) == 2
    meter = money.Meter(tmp_path / "ledger.csv", "1-x")
    meter.charge("raphael", "gpt-5", "high", Usage(10, 0, 10, 0), 0.0)
    assert run.main(["paid", "--yes"]) == 1  # no hypothesis after the first run
    for name in ("2-x", "3-x"):
        money.Meter(tmp_path / "ledger.csv", name).charge("raphael", "gpt-5", "high", Usage(10, 0, 10, 0), 0.0)
    assert run.main(["paid", "--yes", "--hypothesis", "h"]) == 1  # three runs done: the person's read comes first


# ── the schemas are strict, the prompt tells no story ───────────────────────────────────────────


def walk(node: Any, path: str = "") -> list[str]:
    bad = []
    if isinstance(node, dict):
        if node.get("type") == "object":
            props = node.get("properties")
            if node.get("additionalProperties") is not False:
                bad.append(f"{path}: additionalProperties is not false")
            if props is not None and sorted(node.get("required") or []) != sorted(props):
                bad.append(f"{path}: not every property is required")
        for key in ("default", "$ref", "allOf", "oneOf"):
            if key in node:
                bad.append(f"{path}: {key} is not allowed in strict mode")
        for k, v in node.items():
            bad += walk(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            bad += walk(v, f"{path}[{i}]")
    return bad


def test_every_tool_is_strict() -> None:
    assert walk(schema.put_schema()) == []
    for spec in agent.tool_specs():
        assert spec["strict"] and walk(spec["parameters"]) == [], spec["name"]


def test_a_put_clip_is_davincis_plan_and_design_in_one() -> None:
    item = schema.put_schema()["properties"]["clips"]["items"]["properties"]
    plan = set(davinci_schema.MenuW.model_fields)
    assert plan <= set(item) and {"id", "ir", "sound"} <= set(item)
    assert "cinematography" in item["ir"]["properties"] and "first_frame" in item["ir"]["properties"]


def test_the_prompt_tells_no_story_and_delegates_nothing() -> None:
    text = agent.prompt()
    assert not re.search(r"Kasun|Anudi|Colombo|umbrella|three-wheeler|\btea\b|marriage|father", text, re.IGNORECASE)
    assert not re.search(r"plan_coverage|write_clips|clip writer|coverage planner|\bcheck`", text)
    for tool in agent.TOOLS:
        assert f"`{tool}" in text, tool


def test_the_checks_are_davincis(tmp_path: Path) -> None:
    import davinci.checks

    assert agent.checks is davinci.checks  # R2: one copy, both labs judged the same


def test_reports_that_are_raphaels_are_named_his_to_fix(tmp_path: Path) -> None:
    from davinci.rehearsal import edit_plan

    long_line = {**rehearsal.complete(MENU[9]), "take_s": 4}  # moment 7's reaction carries L16 in a take too short for it
    clips = [rehearsal.complete(r) for r in MENU]
    clips[9] = long_line
    scripted(tmp_path, [("write_edit_plan", edit_plan()), ("put_clips", {"clips": clips})])
    result = next(r for r in trace(tmp_path) if r.get("tool") == "put_clips")["result"]
    assert "Yours to fix" in result and "clock [c10]" in result and "nothing to do" not in result


def test_an_overrun_names_its_blocks_and_says_to_split_them(tmp_path: Path) -> None:
    from davinci.rehearsal import edit_plan

    clips = [rehearsal.complete(r) for r in MENU]
    clips[10] = {**clips[10], "take_s": 4}  # moment 7's single over b17-b19 in a take too short
    scripted(tmp_path, [("write_edit_plan", edit_plan()), ("put_clips", {"clips": clips})])
    result = next(r for r in trace(tmp_path) if r.get("tool") == "put_clips")["result"]
    assert "c11 carries blocks b17, b18, b19" in result and "Split those blocks" in result
