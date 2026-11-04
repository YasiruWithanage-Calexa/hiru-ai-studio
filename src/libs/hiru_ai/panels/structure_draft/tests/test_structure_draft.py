"""structure_draft: the drafting agents of a structure build side by side, each job answered or sent to the rules."""
from __future__ import annotations

from typing import Any

from hiru_ai.core import llm
from hiru_ai.core.context import RunContext
from hiru_ai.core.testing import RoutedChatModel
from hiru_ai.panels.structure_draft import graph


def route(messages: list[Any]) -> str:
    system = str(messages[0].content)
    return "architect" if "Script Architect" in system else "prose" if "episode" in system.lower() else "looks"


def job(member: str, key: str, **inp: Any) -> dict[str, Any]:
    return {"member": member, "key": key, "input": inp}


EPISODE = {"number": 1, "title": "Home", "scenes": [{"number": 1, "heading": "INT. KITCHEN - DAY",
                                                      "blocks": [{"kind": "action", "text": "Nimal comes home."}]}]}


NAMES = {"synopsis": "Two sentences.", "scenes": [{"number": 1, "title": "Nimal comes home"}]}


def run(jobs: list[dict[str, Any]], replies: dict[str, list[Any]], manifest: Any = None) -> list[dict[str, Any]]:
    with llm.use_models(RoutedChatModel(routes=replies, choose=route)):
        out = graph.build(RunContext(), manifest=manifest).invoke({"items": jobs})
    return list(out["outputs"])  # type: ignore[no-any-return]


def test_a_job_is_answered_by_the_member_it_names_and_results_follow_job_order():
    results = run([job("architect", "ep1", **EPISODE), job("architect", "ep2", **EPISODE)],
                  {"architect": [NAMES, NAMES]})
    got = [(r["member"], r["key"], r["ok"]) for r in results]
    assert got == [("architect", "ep1", True), ("architect", "ep2", True)]
    assert results[0]["output"].synopsis == "Two sentences."


def test_an_agent_that_cannot_answer_is_marked_for_the_rules_not_raised():
    results = run([job("architect", "ep1", **EPISODE)], {})
    assert results[0]["ok"] is False and results[0]["output"] is None


def test_a_member_that_is_not_on_the_panel_is_marked_for_the_rules():
    manifest = graph.PanelKit(graph.ID).manifest
    smaller = manifest.model_copy(update={"members": [m for m in manifest.members if m.label != "looks"]})
    results = run([job("looks", "kamala"), job("nobody", "x")], {}, smaller)
    assert [r["ok"] for r in results] == [False, False]


def test_no_jobs_is_an_empty_result():
    assert run([], {}) == []
