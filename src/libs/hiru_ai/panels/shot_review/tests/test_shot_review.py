"""shot_review: the bounded design-and-review loop, with the agents resolved by the manifest."""
from __future__ import annotations

import dataclasses
from typing import Any

from hiru_ai.core import llm, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.registry import Registry
from hiru_ai.core.testing import RoutedChatModel
from hiru_ai.panels.shot_review import graph

DESIGN_1 = {"shots": [{"number": 1, "note": "first"}]}
DESIGN_2 = {"shots": [{"number": 1, "note": "revised"}]}


def route(messages: list[Any]) -> str:
    return "critic" if "review the camera design" in str(messages[0].content) else "writer"


class Seams:
    """What the producer system supplies: how to ask, what a note is, and when a revision is kept."""

    def __init__(self, free: list[str] | None = None, keep: bool = True) -> None:
        self.written: list[list[str] | None] = []
        self.reviewed: list[Any] = []
        self.free, self.keep = free or [], keep

    def write(self, ask: Any, brief: dict[str, Any], notes: list[str] | None) -> Any:
        self.written.append(notes)
        return ask({"production": "P", "scene": brief["scene"] + (" | " + "; ".join(notes) if notes else "")}).shots

    def critique(self, ask: Any, brief: dict[str, Any], draft: Any) -> list[str]:
        self.reviewed.append(draft)
        answer = ask({"scene_number": 1, "heading": "INT. STALL", "drafts": [str(draft)], "free": self.free})
        return list(answer.notes)

    def accept(self, brief: dict[str, Any], draft: Any, revised: Any) -> Any:
        return revised if self.keep else draft


def run(writer: list[Any], critic: list[Any], seams: Seams, registry: Registry | None = None,
        manifest: Any = None) -> Any:
    model = RoutedChatModel(routes={"writer": list(writer), "critic": list(critic)}, choose=route)
    with llm.use_models(model):
        built = graph.build(RunContext(), registry, manifest, write=seams.write, critique=seams.critique,
                            accept=seams.accept)
        return built.invoke({"brief": {"scene": "S1"}})


def test_notes_lead_to_exactly_one_revision_that_is_kept_when_accepted():
    seams = Seams()
    out = run([DESIGN_1, DESIGN_2], [{"acceptable": False, "notes": ["S01: closer"]}], seams)
    assert out["draft"] == DESIGN_2["shots"] and out["rounds"] == 1
    assert seams.written == [None, ["S01: closer"]] and len(seams.reviewed) == 1  # the revision is not reviewed again


def test_a_revision_the_free_checks_do_not_like_leaves_the_first_draft():
    out = run([DESIGN_1, DESIGN_2], [{"acceptable": False, "notes": ["S01: closer"]}], Seams(keep=False))
    assert out["draft"] == DESIGN_1["shots"] and out["rounds"] == 1


def test_a_content_critic_means_one_draft_and_no_second_ask():
    seams = Seams()
    out = run([DESIGN_1], [{"acceptable": True, "notes": []}], seams)
    assert out["draft"] == DESIGN_1["shots"] and out["rounds"] == 0 and seams.written == [None]


def test_a_critic_that_cannot_answer_is_content_and_the_first_draft_stands():
    out = run([DESIGN_1], [], Seams())
    assert out["draft"] == DESIGN_1["shots"] and out["notes"] == [] and out["rounds"] == 0


def test_the_loop_has_a_ceiling_from_the_manifest():
    manifest = graph.PanelKit(graph.ID).manifest
    assert manifest.max_rounds == 1
    never = manifest.model_copy(update={"max_rounds": 0})
    out = run([DESIGN_1], [{"acceptable": False, "notes": ["always something"]}], Seams(), manifest=never)
    assert out["rounds"] == 0 and out["draft"] == DESIGN_1["shots"]


def test_a_critic_switched_off_means_no_review_at_all():
    reg = parts._registry()
    clone = Registry(reg.root, reg.package)
    clone.components = dict(reg.components)
    comp = clone.components[("agent", "shot_critic")]
    clone.components[("agent", "shot_critic")] = dataclasses.replace(
        comp, manifest=comp.manifest.model_copy(update={"status": "disabled"}))
    seams = Seams()
    out = run([DESIGN_1], [{"acceptable": False, "notes": ["never asked"]}], seams, registry=clone)
    assert out["draft"] == DESIGN_1["shots"] and seams.reviewed == [] and out["rounds"] == 0


def test_a_writer_that_cannot_answer_raises_so_the_producer_can_fall_back_to_its_rules():
    try:
        run([], [], Seams())
    except RuntimeError:
        return
    raise AssertionError("the writer has no fallback: the system decides what to do")
