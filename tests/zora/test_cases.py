"""Zora's replay cases, offline (plan/2026-11-06e Phase 0, 2): each case's recorded conductor answer goes through the
real kernel and dependency graph, and everything code alone can prove is checked. What needs the author or the reply
(`expect.needs`) is the lab's (Phase 3) and the evals' (Phase 9)."""
from __future__ import annotations

import json
from typing import Any

import pytest

from contracts.zora import effects as E
from contracts.zora import ops as O
from hiru_ai.steps.zora.zora_deps.logic import plan_tasks, recut_guard
from hiru_ai.steps.zora.zora_kernel.logic import ZoraKernel
from tests.zora.world import ROOT, doc, words

CASES = json.loads((ROOT / "tests" / "eval" / "zora" / "cases.json").read_text(encoding="utf-8"))["cases"]
LANES = ("chat", "clarify", "edit", "craft", "shape", "options", "translate", "cannot", "undo")


def test_the_cases_cover_the_plans_requests_with_a_held_out_split_and_say_what_the_old_chat_does():
    assert len(CASES) >= 10 and len({c["id"] for c in CASES}) == len(CASES)
    assert {c["split"] for c in CASES} == {"tune", "heldout"}
    assert sum(c["split"] == "heldout" for c in CASES) >= 4
    assert {c["scene"] for c in CASES} == {"episode1", "arrival", "father_refuses"}
    for c in CASES:
        assert c["old_chat"]["what"], c["id"]
        assert c["expect"]["lane"] in LANES


def _turns(case: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    if "turns" in case:
        return [(t["person"], t["conduct"]) for t in case["turns"]]
    return [(case["message"], case["conduct"])]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_the_recorded_conductor_answer_is_a_transcription_and_code_does_the_rest(case: dict[str, Any]):
    start = doc(case["scene"])
    k = ZoraKernel(start)
    first = json.dumps(k.export(), sort_keys=True)
    expect = case["expect"]
    results = []
    for message, conduct in _turns(case):
        assert conduct["lane"] in LANES
        for op in conduct["ops"]:
            assert not O.invented(op, message), f"{case['id']}: the conductor composed {op}"
        for task in conduct["tasks"]:
            assert [E.normalize_effect(e) for e in task["writes"]] == task["writes"], task["writes"]
            assert all(E.can_produce("author", e) for e in task["writes"])
            assert all(1 <= n <= len(start.shots) + len(conduct["ops"]) for n in task["scope"])
        before = len(k.export()["shots"])
        r = k.apply(conduct["ops"], by="conductor")
        results.append(r)
        if expect.get("ops_land", conduct["ops"] != []):
            assert not r.rejected, r.rejected
        stale = plan_tasks(k, r.changes)
        assert recut_guard(conduct["lane"], "", before, stale) == ""
        if "deps_writes" in expect:
            got = {e for t in stale.tasks for e in t.writes}
            assert got == set(expect["deps_writes"]), got
        if "deps_scope" in expect and stale.tasks:
            assert sorted(k.number_of(h) or 0 for t in stale.tasks for h in t.scope) == expect["deps_scope"]
        if expect.get("declared"):
            assert {e for t in conduct["tasks"] for e in t["writes"]} == set(expect["declared"])
    plan = k.export()
    if conduct["lane"] == "undo":  # a revision restored in code: here, the kernel's own exact undo
        for r in reversed(results[:-1]):
            k.undo(r)
        plan = k.export()
    unchanged = json.dumps(plan, sort_keys=True) == first
    if expect.get("plan_unchanged") or expect.get("plan_unchanged_by_conductor") or expect.get("plan_equals_start"):
        assert unchanged
    if "added" in expect:
        a = expect["added"]
        assert any(x["shot"] == a["shot"] and x["kind"] == a["kind"] and x["who"] == a["who"] for x in plan["added"])
    for line, n in (expect.get("line_in") or {}).items():
        assert line in plan["shots"][n - 1]["lines"]
    for n, fields in (expect.get("shot_field") or {}).items():
        for f, v in fields.items():
            assert plan["shots"][int(n) - 1][f] == v
    for f, v in (expect.get("treatment") or {}).items():
        assert plan["treatment"][f] == v
    if "locked" in expect:
        assert k.person().locked == expect["locked"]
    if expect.get("lines_verbatim"):
        assert words(k.doc()) == words(start)
