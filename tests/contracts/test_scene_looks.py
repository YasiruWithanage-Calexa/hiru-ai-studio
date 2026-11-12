"""Scene looks contracts (plan/2026-11-12c phase 1), held to the lab's Ekama answer (looks1, 2026-11-12): nothing to
fix; Dinu keeps his clothes across the flashback; voice-only Aruni gets no look; Nimal is found in his last clothes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from contracts import canon_refine as cr
from contracts import scene_looks as sl
from contracts.breakdown.schema import Breakdown

F = Path(__file__).resolve().parents[1] / "fixtures" / "canon_refine"


def _load(name: str) -> Any:
    return json.loads((F / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ekama() -> tuple[Breakdown, dict[str, Any], sl.Truth, sl.LooksAnswer]:
    bd = Breakdown.model_validate(_load("ekama.json")["memory"])
    data, truth = sl.from_breakdown(bd, cr.Answer.model_validate(_load("run2.json")))
    return bd, data, truth, sl.LooksAnswer.model_validate(_load("looks1_ekama.json"))


def test_looks1_has_nothing_to_fix(ekama: Any) -> None:
    _, data, truth, a = ekama
    found = sl.check(a, [s["id"] for s in data["scenes"]], truth)
    assert [f for f in found if f.level == "fix"] == []


def test_the_input_carries_presence_and_the_refined_wardrobe(ekama: Any) -> None:
    _, data, truth, _ = ekama
    dinu = next(p for p in data["people"] if p["id"] == "C01")
    assert dinu["base_wardrobe"] and dinu["appearance"]
    assert truth.on_screen is not None and "C03" in truth.on_screen["E01-S01"]  # a body is on screen
    assert not any("C0" in s["text"] for s in data["episodes"])  # ids become names


def test_a_voice_only_person_with_a_look_and_a_condition_in_an_outfit_are_fixes(ekama: Any) -> None:
    _, data, truth, a = ekama
    a = a.model_copy(deep=True)
    voice_only = next(sid for sid, on in truth.on_screen.items() if "C02" not in on)
    sw = next(s for s in a.scenes if s.scene == voice_only)
    look = next(lk for lk in a.looks if lk.person == "C02")
    sw.on_screen.append(sl.Wear(person="C02", look=look.id, condition="", why="x"))
    look.outfit += ", soaked by rain"
    found = sl.check(a, [s["id"] for s in data["scenes"]], truth)
    assert any("not on screen" in f.message for f in found if f.level == "fix")
    assert any("condition belongs to the scene" in f.message for f in found if f.level == "fix")


def test_a_missing_scene_and_a_foreign_look_are_fixes(ekama: Any) -> None:
    _, data, truth, a = ekama
    a = a.model_copy(deep=True)
    a.story = a.story[1:]
    sw = a.scenes[0]
    other = next(lk for lk in a.looks if lk.person != sw.on_screen[0].person)
    sw.on_screen[0] = sl.Wear(person=sw.on_screen[0].person, look=other.id, condition="", why="x")
    found = sl.check(a, [s["id"] for s in data["scenes"]], truth)
    assert any("appears 0 times in `story`" in f.message for f in found)
    assert any("which is" in f.message and "'s" in f.message for f in found)


def test_a_change_inside_continuous_time_is_for_review(ekama: Any) -> None:
    _, data, truth, a = ekama
    a = a.model_copy(deep=True)
    on = {sw.scene: {w.person: w for w in sw.on_screen} for sw in a.scenes}
    first, then = next((x, y) for x in on for y in on if x != y and set(on[x]) & set(on[y]))
    next(s for s in a.story if s.scene == then).continuous_with = first
    wear = on[then][sorted(set(on[first]) & set(on[then]))[0]]
    extra = sl.Look(
        id=f"{wear.person}-9",
        person=wear.person,
        name="Other",
        outfit="a grey shirt",
        hair="",
        makeup="",
        accessories="",
        why="x",
    )
    a.looks.append(extra)
    wear.look = extra.id
    found = sl.check(a, [s["id"] for s in data["scenes"]], truth)
    assert any(f.level == "review" and "calls continuous" in f.message for f in found)


def test_rows_give_draft_looks_with_episode_ranges_and_scene_looks(ekama: Any) -> None:
    bd, _, truth, a = ekama
    entity_of = {p: f"ent-{p}" for p in truth.people}
    scene_row_of = {s.id: s.row_id for s in bd.scenes}
    looks, scenes = sl.rows(a, truth, entity_of, scene_row_of)
    assert looks and all(lk["ranges"] == [{"from": 1, "to": 1}] for lk in looks)
    names = {(lk["entity_id"], lk["name"].lower()) for lk in looks}
    assert len(names) == len(looks)
    assert scenes and all((s["entity_id"], s["look_name"].lower()) in names for s in scenes)
    assert {s["scene_id"] for s in scenes} <= set(scene_row_of.values())
    nimal = [s for s in scenes if s["entity_id"] == "ent-C03"]
    assert len({s["look_name"] for s in nimal}) == 1  # found in the clothes he was last seen in


def test_ranges_join_consecutive_episodes() -> None:
    assert sl.ranges([3, 1, 2, 5, 0]) == [{"from": 1, "to": 3}, {"from": 5, "to": 5}]


def test_a_long_production_is_split_by_episode() -> None:
    scenes = [{"id": f"E{e:02d}-S01", "episode": e, "heading": "x", "script": ["word " * 400]} for e in (1, 2, 3)]
    data = {"episodes": [{"episode": e, "text": ""} for e in (1, 2, 3)], "people": [], "scenes": scenes, "timeline": []}
    got = sl.parts(data, budget=900)
    assert [[s["episode"] for s in p["scenes"]] for p in got] == [[1], [2], [3]]
    assert sl.parts(data) == [data]


def test_from_tables_reads_today_s_rows() -> None:
    data, truth = sl.from_tables(
        [{"number": 1, "title": "One", "synopsis": "s"}],
        [
            {
                "key": "E01-S01",
                "episode": 1,
                "heading": "INT. HOUSE",
                "title": "t",
                "place": "House",
                "script": [{"kind": "action", "text": "Kasun cooks."}, {"kind": "dialogue", "line_id": "l1"}],
            }
        ],
        {"E01-S01": [{"id": "l1", "speaker": "Kasun", "text": "Hari."}]},
        [{"code": "C01", "name": "Kasun", "card": {"wardrobe": "an apron"}}],
    )
    assert data["scenes"][0]["script"] == ["Kasun cooks.", "Kasun: Hari."]
    assert truth.on_screen is None and truth.episode_of == {"E01-S01": 1}
