"""The lab, offline (plan/2026-11-06e Phase 3): the answer schemas are strict, the pipeline scores recorded answers,
the money rules hold, and the prompts are not fitted to the cases' wording."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from contracts.zora import effects as E
from contracts.zora import ops as O
from zora import run, schema, turn

CASES = {c["id"]: c for c in run.cases()}


def _strict(node: Any, where: str = "$") -> None:
    if isinstance(node, dict):
        if node.get("type") == "object" or (isinstance(node.get("type"), list) and "object" in node["type"]):
            assert node.get("additionalProperties") is False, where
            assert set(node["required"]) == set(node["properties"]), where
        for k, v in node.items():
            _strict(v, f"{where}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _strict(v, f"{where}[{i}]")


def test_the_answer_schemas_are_strict_and_name_only_what_each_role_may_use():
    _strict(schema.conductor_schema())
    _strict(schema.author_schema())
    author_ops = set(schema.author_schema()["properties"]["ops"]["items"]["properties"]["op"]["enum"])
    assert author_ops == set(O.ops_for("author")) and "end.set" not in author_ops and "lock" not in author_ops
    conductor_ops = set(schema.conductor_schema()["properties"]["ops"]["items"]["properties"]["op"]["enum"])
    assert "end.set" in conductor_ops and "block.set" not in conductor_ops


def test_a_flat_answer_becomes_an_operation():
    flat = {k: None for k in schema.OP_FIELDS}
    op = schema.to_op({**flat, "op": "ir.set", "shot": "S03", "path": "beats", "value": '[{"time": "0-4s"}]'})
    assert op == {"op": "ir.set", "shot": "S03", "path": "beats", "value": [{"time": "0-4s"}]}
    op = schema.to_op({**flat, "op": "sound.set", "shot": "S01", "field": "silence", "value": "true"})
    assert op["value"] is True


def test_a_recorded_answer_is_scored_and_an_empty_one_is_never_counted_as_done():
    case = CASES["approach-colder"]
    out = turn.run_turn(case, run.Recorded(case["id"]), arm="A")
    checks = turn.score(case, out)
    assert turn.passed(checks) and any(c.startswith("Treatment: approach") for c in out.changes)
    # it changed the approach, lenses and an angle, not the movement it was also asked for: re-tasked once, then reported
    assert out.calls == {"author": 2} and out.undelivered == ["the shots' cinematography (camera design)"]
    empty = turn.run_turn(case, run.Recorded("no-such-case"), arm="A")
    assert not turn.passed(turn.score(case, empty)) and empty.calls == {"author": 2}  # one re-task, then reported
    assert "the treatment's approach" in empty.undelivered and not empty.changes


def test_arm_b_calls_only_the_seats_that_own_an_asked_effect():
    case = CASES["approach-colder"]
    out = turn.run_turn(case, run.Recorded(case["id"]), arm="B")
    assert set(out.calls) == {"cinematography"}
    assert turn.passed(turn.score(case, out))


def test_options_are_tried_on_a_copy_and_the_plan_is_left_alone():
    case = CASES["two-ways-to-open"]
    out = turn.run_turn(case, run.Recorded(case["id"]), arm="A")
    assert len(out.proposals) == 2 and not out.changes


def test_the_budget_refuses_a_call_that_could_pass_it_and_the_cache_answers_for_free(tmp_path: Path, monkeypatch: Any):
    monkeypatch.setattr(run, "LEDGER", tmp_path / "ledger.csv")
    monkeypatch.setattr(run, "CACHE", tmp_path / "cache")
    run.add_to_ledger({"dollars": f"{run.BUDGET_USD - 0.01:.4f}", "status": "done"})
    paid = run.Paid("t", "c", "h")
    with pytest.raises(run.LabError, match="passes the"):
        paid("author", "system", "user " * 2000, schema.author_schema())
    key = run.key_of("author", "system", "user", schema.author_schema())
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / f"{key}.json").write_text(json.dumps({"notes": "cached", "ops": []}), encoding="utf-8")
    assert paid("author", "system", "user", schema.author_schema())["notes"] == "cached"
    assert paid._client is None  # no client was ever made


def test_an_unpriced_model_is_refused():
    with pytest.raises(run.LabError):
        run.price_of("gpt-9-ultra")


def test_the_prompts_are_not_fitted_to_the_cases_and_name_every_effect():
    conductor = turn.conductor_system()
    author = (run.LAB / "prompts" / "author.md").read_text(encoding="utf-8")
    for case in CASES.values():
        message = case.get("message") or case["turns"][-1]["person"]
        assert message.lower() not in (conductor + author).lower(), case["id"]
    for effect in E.WRITES:
        if effect != "end_state":
            assert effect in conductor, effect
    assert len(conductor) <= 7_500 and len(author) <= 3_000  # Nova's charter budgets: consolidate, never bump
