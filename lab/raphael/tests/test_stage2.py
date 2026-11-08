"""Offline tests of stage 2, the cinematic pass (plan/2026-11-08e phase 0c): no model, no network, no database.

Run from the repo root:  .venv/Scripts/python.exe -m pytest lab/raphael/tests -q
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from davinci import checks, money
from davinci.brain import Call, Reply
from davinci.money import Usage
from raphael import agent, rehearsal, rehearsal2, run, schema, stage2
from raphael.rehearsal2 import RUN3, extra


def fresh() -> Any:
    return stage2.load_stage1(RUN3)


def rehearsed(tmp_path: Path) -> tuple[stage2.CinematicPass, agent.Outcome]:
    backend = rehearsal2.CinematicRehearsal()
    cin = stage2.CinematicPass(rehearsal.reading(), fresh(), backend, money.Meter(tmp_path / "p.csv", "t"), tmp_path / "run")
    backend.bind(cin)
    return cin, cin.run()


def trace(tmp_path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in (tmp_path / "run" / "trace.jsonl").read_text(encoding="utf-8").splitlines()]


class Scripted:
    """Sends a fixed list of (tool, args-builder) turns, then idles. A builder gets the pass, so clips can copy its looks."""

    def __init__(self, turns: list[tuple[str, Any]]) -> None:
        self.turns, self.i, self.agent = turns, 0, None

    def step(self, **_: Any) -> Reply:
        if self.i >= len(self.turns):
            return Reply(id="idle", text="", usage=Usage(1000, 0, 10, 0))
        name, args = self.turns[self.i]
        self.i += 1
        body = args(self.agent) if callable(args) else args
        return Reply(id=f"r{self.i}", calls=[Call(id=f"c{self.i}", name=name, args=json.dumps(body))],
                     usage=Usage(1000, 0, 100, 0))

    def structured(self, **_: Any) -> Reply:
        raise AssertionError("no worker")


def scripted(tmp_path: Path, turns: list[tuple[str, Any]], **cfg: Any) -> tuple[stage2.CinematicPass, agent.Outcome]:
    backend = Scripted(turns)
    cin = stage2.CinematicPass(rehearsal.reading(), fresh(), backend, money.Meter(tmp_path / "p.csv", "t"), tmp_path / "run",
                               stage2.stage2_config(**cfg))
    backend.agent = cin
    return cin, cin.run()


def insert_on(anchor: str, **kw: Any) -> Any:
    """A good cinematic clip on `anchor`, built from the pass's own state when the turn is sent."""
    args = {"role": "insert", "technique": "rack_focus", "blend": "cut_in", "size": "INSERT", "setup": "N",
            "priority": "should", "why": "A detail the must clips do not show.", "action": "a hand rests on the counter", **kw}
    return lambda a: {"clips": [extra(a.work, anchor, **args)]}


def results(tmp_path: Path, tool: str) -> list[str]:
    return [r["result"] for r in trace(tmp_path) if r.get("tool") == tool]


# ── the rehearsal: the plan's script, the real loop, run 3's real must bin ───────────────────────


def test_the_rehearsal_finishes_within_12_turns_with_nothing_blocking(tmp_path: Path) -> None:
    cin, out = rehearsed(tmp_path)
    assert out.finished and not checks.blocking(out.faults) and out.turns <= 12 == stage2.stage2_config().max_turns
    assert len(stage2.extras(cin.work)) == 5 and cin.work.counts()["take_s"] <= stage2.cap_s(cin.reading) == 120


def test_stage_1s_clips_are_byte_identical_after_stage_2(tmp_path: Path) -> None:
    before = {c.id: c.model_dump_json() for c in fresh().clips}
    cin, _ = rehearsed(tmp_path)
    after = {c.id: c.model_dump_json() for c in cin.work.clips if not stage2.is_extra(c)}
    assert after == before and cin.changed_must() == []


def test_the_script_refuses_a_must_id_a_same_angle_and_three_in_a_moment_then_one_call_repairs(tmp_path: Path) -> None:
    rehearsed(tmp_path)
    puts, finishes = results(tmp_path, "put_extras"), results(tmp_path, "finish")
    assert "c05 is a must clip of stage 1 and is locked" in puts[0] and "Cinematic clips: 0" in puts[0]
    assert "like its anchor c07: that is an alternate" in puts[1] and "Moment 7 has 4 cinematic clips; at most 3" in puts[1]
    assert finishes[0].startswith("Refused") and finishes[-1].startswith("Finished")
    assert puts[2].startswith("Replaced c16") and "Nothing blocks" in puts[2]  # both faults cured by ONE call


def test_the_pass_asks_no_other_model_and_shows_no_money(tmp_path: Path) -> None:
    cin, out = rehearsed(tmp_path)
    rows = trace(tmp_path)
    assert out.finished and {r["slot"] for r in rows if "slot" in r} == {"cinematic"}
    from cinematic import pack

    ours = cin.opening.replace(pack.message(cin.reading), "")  # the scene's own text (a director's note) is the owner's
    text = " ".join(r.get("result", "") for r in rows) + cin.system + ours
    assert not re.search(r"\$\d|budget|dollar|spent|cost", text, re.IGNORECASE)


def test_the_opening_has_the_cut_the_locked_bin_the_looks_and_the_room(tmp_path: Path) -> None:
    cin, _ = scripted(tmp_path, [])
    for part in ("<intended_cut>", "<must_bin>", "LOCKED", "<looks>", "WORD FOR WORD", "<room>", "50 s left", "<voice_only>",
                 "turning moments first", "review of EVERY moment"):
        assert part in cin.opening, part
    assert all(c.id in cin.opening for c in cin.work.clips)


# ── the tools ────────────────────────────────────────────────────────────────────────────────────


def test_remove_extras_refuses_a_must_clip(tmp_path: Path) -> None:
    cin, _ = scripted(tmp_path, [("put_extras", insert_on("c07")), ("remove_extras", {"clip_ids": ["c07", "c15"]})])
    assert cin.work.by_id("c07") is not None and cin.work.by_id("c15") is None
    assert "c07 is a must clip of stage 1 and is locked" in results(tmp_path, "remove_extras")[0]


def test_the_schema_refuses_a_must_cinematic_clip(tmp_path: Path) -> None:
    def must(a: Any) -> dict[str, Any]:
        body = insert_on("c07")(a)
        body["clips"][0]["priority"] = "must"
        return body

    cin, _ = scripted(tmp_path, [("put_extras", must)])
    assert not stage2.extras(cin.work) and "Nothing was changed" in results(tmp_path, "put_extras")[0]
    assert schema.extras_schema()["properties"]["clips"]["items"]["properties"]["priority"]["enum"] == ["should", "nice"]


def test_a_replace_keeps_the_id_and_the_slate_moves_with_the_setup(tmp_path: Path) -> None:
    def again(a: Any) -> dict[str, Any]:
        body = insert_on("c07", setup="F", technique="slow_creep")(a)
        body["clips"][0]["id"] = "c15"
        return body

    cin, _ = scripted(tmp_path, [("put_extras", insert_on("c07")), ("put_extras", again)])
    e = cin.work.by_id("c15")
    assert isinstance(e, schema.Extra) and e.technique == "slow_creep" and e.slate == "1F-2"  # next take in the anchor's setup
    assert cin.changed_must() == []


def test_an_anchor_in_another_moment_is_refused_and_a_transition_may_reach_the_next(tmp_path: Path) -> None:
    def moved(blend: str) -> Any:
        def build(a: Any) -> dict[str, Any]:
            body = insert_on("c07", blend=blend)(a)
            body["clips"][0]["anchor"] = ["c13"]  # moment 8; the clip is in moment 7
            return body
        return build

    _, _ = scripted(tmp_path, [("put_extras", moved("cut_in"))])
    assert "its anchor c13 is in moment 8" in results(tmp_path, "put_extras")[0]
    shutil.rmtree(tmp_path / "run")
    _, _ = scripted(tmp_path, [("put_extras", moved("transition"))])
    assert "is in moment 8" not in results(tmp_path, "put_extras")[0]


def test_an_unknown_or_cinematic_anchor_is_refused(tmp_path: Path) -> None:
    def on_extra(a: Any) -> dict[str, Any]:
        body = insert_on("c07", technique="slow_creep", setup="P")(a)
        body["clips"][0]["anchor"] = ["c15"]
        return body

    scripted(tmp_path, [("put_extras", insert_on("c07")), ("put_extras", on_extra)])
    assert "anchor c15 is not a must clip" in results(tmp_path, "put_extras")[1]


def test_a_cinematic_clip_that_speaks_is_refused(tmp_path: Path) -> None:
    def speaking(a: Any) -> dict[str, Any]:
        body = insert_on("c07")(a)
        body["clips"][0].update({"speaks": True, "lines": ["L13"], "blocks": [13]})
        return body

    scripted(tmp_path, [("put_extras", speaking)])
    assert "performs a line: a cinematic clip is silent" in results(tmp_path, "put_extras")[0]


def test_stage_2s_cap_is_twice_the_scene_and_there_is_no_count_guide(tmp_path: Path) -> None:
    moments = [("c01", "M"), ("c03", "N"), ("c04", "P"), ("c05", "Q"), ("c07", "R"), ("c08", "S"), ("c11", "T")]

    def seven(take: int) -> Any:
        def build(a: Any) -> dict[str, Any]:
            clips = [extra(a.work, anchor, role="insert", technique="rack_focus", blend="cut_in", size="INSERT", setup=s,
                           priority="nice", why="a detail", action="a hand rests on the counter") for anchor, s in moments]
            return {"clips": [{**c, "take_s": take} for c in clips]}
        return build

    cin, _ = scripted(tmp_path, [("put_extras", seven(4))])
    report = results(tmp_path, "put_extras")[0]
    assert cin.work.counts()["take_s"] == 98 and "Nothing blocks" in report and "guide" not in report  # 98 s: within 120 s
    shutil.rmtree(tmp_path / "run")
    cin, out = scripted(tmp_path, [("put_extras", seven(8)), ("finish", {"blend_notes": [], "moment_review": []})])
    report = results(tmp_path, "put_extras")[0]
    assert cin.work.counts()["take_s"] == 126 and "may hold 120 s" in report and not out.finished  # over 2x: blocking


def test_a_screen_and_a_phone_close_up_are_not_reported(tmp_path: Path) -> None:
    def phone(a: Any) -> dict[str, Any]:
        body = insert_on("c08", size="ECU", why="The phone lights up and its screen glows on her fingers; the notification "
                         "reads as a buzz.")(a)
        return body

    scripted(tmp_path, [("put_extras", phone)])
    assert "screen text" not in results(tmp_path, "put_extras")[0]
    from raphael import agent as raphael_agent

    assert raphael_agent.DROPPED == ("screen text",)


def review(has: set[int], skip: int = 0, why: str = "a reason") -> list[dict[str, Any]]:
    return [{"moment": n, "earns": n in has, "why": why} for n in range(1, 12) if n != skip]


def test_finish_needs_every_moment_reviewed_and_the_review_to_match(tmp_path: Path) -> None:
    _, out = scripted(tmp_path, [
        ("put_extras", insert_on("c07")),
        ("finish", {"blend_notes": ["c15: cut in"], "moment_review": review({7}, skip=8)}),
        ("finish", {"blend_notes": ["c15: cut in"], "moment_review": review(set())}),
        ("finish", {"blend_notes": ["c15: cut in"], "moment_review": review({7}, why="")}),
        ("finish", {"blend_notes": ["c15: cut in"], "moment_review": review({7})})])
    f = results(tmp_path, "finish")
    assert "moment 8 is not reviewed" in f[0] and "moment 7 says earns false but has cinematic clips" in f[1]
    assert "has no reason" in f[2] and f[3].startswith("Finished") and out.finished


def test_finish_with_no_clip_is_a_review_of_nos(tmp_path: Path) -> None:
    cin, out = scripted(tmp_path, [("finish", {"blend_notes": [], "moment_review": review(set())})])
    assert out.finished and len(cin.review) == 11


def test_finish_needs_a_blend_note_per_clip(tmp_path: Path) -> None:
    _, out = scripted(tmp_path, [("put_extras", insert_on("c07")),
                                 ("finish", {"blend_notes": ["a general note"], "moment_review": review({7})}),
                                 ("finish", {"blend_notes": ["c15: cut in on c07 while L13 plays."], "moment_review": review({7})})])
    finishes = results(tmp_path, "finish")
    assert "no blend note names c15" in finishes[0] and out.finished and out.editor_notes == ["c15: cut in on c07 while L13 plays."]


def test_stage_2_needs_a_finished_stage_1(tmp_path: Path) -> None:
    for name in ("bin.json", "edit_plan.json"):
        shutil.copy(RUN3 / name, tmp_path / name)
    (tmp_path / "outcome.json").write_text(json.dumps({"stopped": "turns", "complete": False}), encoding="utf-8")
    with pytest.raises(ValueError, match="did not finish"):
        stage2.load_stage1(tmp_path)


def test_the_turn_cap_is_12_and_saves_the_pass_marked_incomplete(tmp_path: Path) -> None:
    cin, out = scripted(tmp_path, [("read_bin", {"moment": 0})] * 20)
    assert out.stopped == "turns" and out.turns == 12
    run.write_result2(tmp_path / "out", cin.reading, cin, out, cin.meter, "test", "3-x", None)
    saved = json.loads((tmp_path / "out" / "outcome.json").read_text(encoding="utf-8"))
    assert saved["complete"] is False and saved["stage"] == 2 and saved["changed_must"] == []
    assert "INCOMPLETE" in (tmp_path / "out" / "bin.html").read_text(encoding="utf-8")


def test_read_bin_marks_locked_and_cinematic(tmp_path: Path) -> None:
    scripted(tmp_path, [("put_extras", insert_on("c07")), ("read_bin", {"moment": 7})])
    listing = results(tmp_path, "read_bin")[0]
    assert "c07" in listing and "LOCKED" in listing and "c15" in listing and "CINEMATIC anchor c07 blend cut_in" in listing


# ── the schemas, the prompts ─────────────────────────────────────────────────────────────────────


def test_every_stage_2_tool_is_strict(tmp_path: Path) -> None:
    from raphael.tests.test_lab import walk

    cin, _ = scripted(tmp_path, [])
    assert [s["name"] for s in cin.specs()] == list(stage2.TOOLS)
    for spec in cin.specs():
        assert spec["strict"] and walk(spec["parameters"]) == [], spec["name"]
    item = schema.extras_schema()["properties"]["clips"]["items"]["properties"]
    assert {"anchor", "blend", "ir", "sound", "id"} <= set(item) and item["blend"]["enum"] == list(schema.BLENDS)


def test_the_stage_2_prompt_tells_no_story_and_names_its_tools() -> None:
    text = agent.prompt("cinematic")
    assert not re.search(r"Kasun|Anudi|Colombo|umbrella|three-wheeler|\btea\b|marriage|father", text, re.IGNORECASE)
    for tool in stage2.TOOLS:
        assert f"`{tool}" in text, tool
    for blend in schema.BLENDS:
        assert f"`{blend}`" in text, blend


def test_the_must_only_prompt_is_s1_and_runs_1_to_3_keep_theirs() -> None:
    must, old = agent.prompt("raphael_must"), agent.prompt("raphael")
    assert "Priority: always `must`" in must and "cinematic pass" in must
    assert "`should` is an alternate angle" in old and agent.Config().prompt == "raphael"


# ── the commands ─────────────────────────────────────────────────────────────────────────────────


def test_stage2_rehearse_builds_no_client_and_writes_two_layers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import cinematic.run as cinematic_run

    monkeypatch.setattr(cinematic_run, "client", lambda: (_ for _ in ()).throw(AssertionError("a client was built")))
    monkeypatch.setattr(run, "RUNS", tmp_path)
    assert run.main(["stage2", "rehearse"]) == 0
    folder = tmp_path / "rehearsal_stage2"
    html = (folder / "bin.html").read_text(encoding="utf-8")
    assert "The cinematic layer (stage 2)" in html and html.count("cinematic, optional") == 5 and "Blend notes" in html
    assert "Moment review" in html and "a cap of 120 s (stage 2" in html
    assert "Every must clip is exactly as stage 1 left it" in html and "INCOMPLETE" not in html
    rows = json.loads((folder / "bin.json").read_text(encoding="utf-8"))
    assert {r["stage"] for r in rows} == {1, 2} and all(r["anchor"] and r["blend"] for r in rows if r["stage"] == 2)
    assert run.main(["pick", "--run", str(folder)]) == 0
    assert "One cinematic clip and its anchor" in (folder / "post_test.md").read_text(encoding="utf-8")


def test_a_two_layer_bin_loads_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run, "RUNS", tmp_path)
    run.main(["stage2", "rehearse"])
    folder = tmp_path / "rehearsal_stage2"
    work = stage2.load_stage1(folder)
    assert len(stage2.extras(work)) == 5 and work._next == 20


def test_stage2_paid_needs_yes_a_hypothesis_and_stops_after_three_passes(tmp_path: Path,
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run, "LEDGER", tmp_path / "ledger.csv")
    assert run.main(["stage2", "paid"]) == 2
    money.Meter(tmp_path / "ledger.csv", "4-x").charge("cinematic", "gpt-5", "high", Usage(10, 0, 10, 0), 0.0)
    assert run.main(["stage2", "paid", "--yes"]) == 1  # no hypothesis after the first pass
    for name in ("5-x", "6-x"):
        money.Meter(tmp_path / "ledger.csv", name).charge("cinematic", "gpt-5", "high", Usage(10, 0, 10, 0), 0.0)
    assert run.main(["stage2", "paid", "--yes", "--hypothesis", "h"]) == 1  # three passes: the person's read


def test_stage2_paid_refuses_once_its_budget_is_spent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                      capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(run, "LEDGER", tmp_path / "ledger.csv")
    big = Usage(input_tokens=0, cached_tokens=0, output_tokens=200_000, reasoning_tokens=0)  # gpt-5: $2.00 of output
    money.Meter(tmp_path / "ledger.csv", "4-x").charge("cinematic", "gpt-5", "high", big, 0.0)
    assert run.main(["stage2", "paid", "--yes", "--hypothesis", "h"]) == 1
    assert "Stage 2 has spent" in capsys.readouterr().out


def test_full_needs_yes_a_hypothesis_and_the_persons_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run, "LEDGER", tmp_path / "ledger.csv")
    assert run.main(["full"]) == 2
    assert run.main(["full", "--yes"]) == 1
    for name in ("1-x", "2-x", "3-x"):
        money.Meter(tmp_path / "ledger.csv", name).charge("raphael", "gpt-5", "high", Usage(10, 0, 10, 0), 0.0)
    assert run.main(["full", "--yes", "--hypothesis", "h"]) == 1  # three runs: after the person's read only
