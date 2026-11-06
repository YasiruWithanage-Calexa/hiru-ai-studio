"""adam_problems: the faults code mends itself, and what is left sorted into problems for the fixer ladder
(plan/2026-11-05 T3)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from contracts.adam.plan import CardLine, Moment, SceneScript, ShotCard
from contracts.adam.problems import MAX_PROBLEMS, Problem, kind_of_hole, kind_of_note, problem_line
from hiru_ai.steps.adam.adam_problems import step

HERE = Path(__file__).resolve().parents[1]


def hole(cell: str, card: int = 0, why: str = "a face is not seen") -> dict[str, Any]:
    return {"cell": cell, "kind": cell.split(":")[0], "who": "", "blocks": [], "why": why, "card": card,
            "suggest": "a single"}


def reports(**over: Any) -> dict[str, Any]:
    base = {"fit": {"issues": []}, "coverage": {"cells": [], "holes": []}, "continuity": {"issues": []},
            "feasibility": {"flags": []}}
    return {**base, **over}


def note(ident: str, severity: str, kind: str = "change", card: int = 1, cell: str = "") -> dict[str, Any]:
    return {"id": ident, "lens": "editor", "severity": severity, "kind": kind, "card": card, "cell": cell,
            "note": f"{ident} says so"}


def sorted_(rep: dict[str, Any], notes: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return step.run({"reports": rep, "notes": notes, **extra})


def test_the_example_runs_alone():
    out = step.run(json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8")))
    (only,) = out["problems"]
    assert only["kind"] == "local" and only["note_id"] == "n1" and only["cell"] == "other:2:dasun"


# ── rung 0: code mends ───────────────────────────────────────────────────────────────────────────


def scene_and_plan() -> tuple[SceneScript, list[Moment], list[ShotCard]]:
    scene = SceneScript.model_validate({"cast": ["A", "B"], "blocks": [
        {"index": 0, "kind": "action", "text": "A waits."},
        {"index": 1, "kind": "dialogue", "text": "Hello.", "speaker": "A", "line_id": "L1"},
        {"index": 2, "kind": "dialogue", "text": "Hi.", "speaker": "B", "line_id": "L2"}]})
    moments = [Moment(id="m1", tier="script", serves=["b0"]),
               Moment(id="m2", tier="script", serves=["b1"], lines=["L1"]),
               Moment(id="m3", tier="script", serves=["b2"], lines=["L2"])]
    cards = [ShotCard(number=n, moments=[f"m{n}"], size="MS", take_s=4) for n in (1, 2, 3)]
    return scene, moments, cards


def mend(cards: list[ShotCard]) -> dict[str, Any]:
    scene, moments, _ = scene_and_plan()
    return step.run({"scene": scene.model_dump(mode="json"), "moments": [m.model_dump(mode="json") for m in moments],
                     "cards": [c.model_dump(mode="json", by_alias=True) for c in cards]})


def test_a_line_that_no_card_binds_goes_to_the_card_that_shows_its_moment():
    cards = scene_and_plan()[2]
    cards[2] = cards[2].model_copy(update={"lines": [CardLine(line_id="L2", on_speaker=True, over_whom="")]})
    out = mend(cards)  # L1 is on no card
    assert out["changed"] and "line L1 (A) is bound to card 2" in out["mends"][0]
    assert "no card bound it" in out["mends"][0]
    bound = {c["number"]: [ln["line_id"] for ln in c["lines"]] for c in out["cards"]}
    assert bound == {1: [], 2: ["L1"], 3: ["L2"]}


def test_a_line_on_the_wrong_card_moves_with_its_placement_and_is_never_changed():
    cards = scene_and_plan()[2]
    cards[0] = cards[0].model_copy(update={"lines": [CardLine(line_id="L1", on_speaker=False, over_whom="B")]})
    cards[2] = cards[2].model_copy(update={"lines": [CardLine(line_id="L2", on_speaker=True, over_whom="")]})
    out = mend(cards)
    assert "it was on card 1" in out["mends"][0]
    moved = next(ln for c in out["cards"] if c["number"] == 2 for ln in c["lines"])
    assert moved == {"line_id": "L1", "on_speaker": False, "over_whom": "B"}  # how it plays is the model's, kept


def test_a_plan_whose_lines_are_all_where_they_belong_is_left_alone():
    cards = scene_and_plan()[2]
    cards[1] = cards[1].model_copy(update={"lines": [CardLine(line_id="L1", on_speaker=True, over_whom="")]})
    cards[2] = cards[2].model_copy(update={"lines": [CardLine(line_id="L2", on_speaker=True, over_whom="")]})
    out = mend(cards)
    assert not out["changed"] and out["mends"] == []


# ── sorting what is left ─────────────────────────────────────────────────────────────────────────


def test_a_face_the_plan_never_shows_by_its_own_picture_is_creative_and_one_that_needs_a_card_is_local():
    assert kind_of_hole("other:2:dasun") == "local" and kind_of_hole("stake:dasun:before") == "local"
    assert kind_of_hole("key") == "local" and kind_of_hole("ending") == "local"
    for cell in ("baseline", "subtext:0", "irony:1", "plant"):
        assert kind_of_hole(cell) == "creative", cell
    cells = {"turn:2"}
    assert kind_of_note("add", "turn:2", cells) == "local" and kind_of_note("add", "hands", cells) == "creative"
    assert {kind_of_note(k, "", set()) for k in ("remove", "change", "risk")} == {"local"}


def test_code_faults_come_first_in_the_order_code_found_them_and_each_is_a_problem_with_its_card():
    rep = reports(
        coverage={"cells": [{"id": "baseline"}], "holes": [hole("baseline", 1), hole("other:2:dasun", 6)]},
        fit={"issues": [{"code": "line_overrun", "level": "overrun", "message": "L4 needs 9 s", "card": 7},
                        {"code": "word_budget", "level": "warning", "message": "dense", "card": 2}]},
        continuity={"issues": [{"code": "axis_cross", "where": "cards 3-4", "message": "the line is crossed"},
                               {"code": "teleport", "where": "Anudi at m5", "message": "she jumps"}]},
        feasibility={"flags": [{"code": "mirror", "card": 5, "risk": "mirrors", "why": "a reflection",
                                "fix": "shoot the person", "addressed": False},
                               {"code": "text", "card": 6, "risk": "text", "why": "x", "fix": "y", "addressed": True}]})
    out = sorted_(rep, [])
    got = [(p["code"], p["kind"], p["card"]) for p in out["problems"]]
    assert got == [("hole:baseline", "creative", 1), ("hole:other:2:dasun", "local", 6), ("line_overrun", "local", 7),
                   ("axis_cross", "local", 3), ("mirror", "local", 5)]  # a teleport is the staging's: not a problem
    assert [p["id"] for p in out["problems"]] == ["p1", "p2", "p3", "p4", "p5"]
    assert out["counts"] == {"mechanical": 0, "local": 4, "creative": 1}


def test_only_a_high_note_is_a_problem_and_a_note_that_names_a_holes_cell_is_that_holes_problem():
    rep = reports(coverage={"cells": [{"id": "other:2:dasun"}], "holes": [hole("other:2:dasun", 6)]})
    notes = [note("n1", "high", "add", 6, "other:2:dasun"), note("n2", "medium"), note("n3", "low"),
             note("n4", "high", "add", 2, "hands"), note("n5", "high", "remove", 4)]
    out = sorted_(rep, notes)
    by_id = {p["id"]: p for p in out["problems"]}
    assert len(out["problems"]) == 3
    assert by_id["p1"]["code"] == "hole:other:2:dasun" and by_id["p1"]["note_id"] == "n1"
    assert by_id["p1"]["source"] == "code"
    assert by_id["p2"]["note_id"] == "n4" and by_id["p2"]["kind"] == "creative" and by_id["p2"]["source"] == "note"
    assert by_id["p3"]["note_id"] == "n5" and by_id["p3"]["kind"] == "local" and by_id["p3"]["note_kind"] == "remove"


def test_a_scene_gets_a_few_problems_and_the_rest_are_left_over_in_the_report():
    notes = [note(f"n{i}", "high", card=i) for i in range(1, MAX_PROBLEMS + 3)]
    out = sorted_(reports(), notes)
    assert len(out["problems"]) == MAX_PROBLEMS and len(out["left"]) == 2
    assert [p["note_id"] for p in out["left"]] == [f"n{MAX_PROBLEMS + 1}", f"n{MAX_PROBLEMS + 2}"]
    assert len(sorted_(reports(), notes, limit=3)["problems"]) == 3


def test_a_problem_reads_as_one_line_the_fixer_can_answer_by_id():
    p = Problem(id="p3", kind="local", source="code", code="hole:key", card=8, cell="key",
                text="the key face is not seen")
    assert problem_line(p) == "p3 [local, code -> key] card 8: the key face is not seen"
    bare = p.model_copy(update={"card": 0, "cell": ""})
    assert problem_line(bare) == "p3 [local, code] the scene: the key face is not seen"
