"""The checks hold the Deed gold (the PDF's own plan) clean, and catch each rule when one thing is broken.

    .venv/Scripts/python.exe -m pytest lab/scene_record/tests -q
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "src" / "libs")]

from chain import Writer  # noqa: E402
from checks import check  # noqa: E402
from geometry import P, World  # noqa: E402
from schema import SceneRecord  # noqa: E402

SCENE = json.loads((HERE / "input" / "deed.json").read_text(encoding="utf-8"))
GOLD = json.loads((HERE / "input" / "deed_gold.json").read_text(encoding="utf-8"))


def run(raw: dict[str, Any], scene: dict[str, Any] = SCENE) -> tuple[set[str], Any]:
    rep = check(SceneRecord.model_validate(raw), scene)
    return {f.code for f in rep.blocking}, rep


def gold() -> dict[str, Any]:
    return copy.deepcopy(GOLD)


def shot(raw: dict[str, Any], sid: str) -> dict[str, Any]:
    return next(s for s in raw["shots"] if s["id"] == sid)


def cam(raw: dict[str, Any], cid: str) -> dict[str, Any]:
    return next(c for c in raw["cameras"] if c["id"] == cid)


def cut(raw: dict[str, Any], kid: str) -> dict[str, Any]:
    return next(k for k in raw["cuts"] if k["id"] == kid)


# ── the gold is clean ────────────────────────────────────────────────────────────────────────────────────────────────
def test_gold_has_no_fault() -> None:
    _, rep = run(gold())
    assert not rep.faults, [f.line() for f in rep.faults]


def test_screen_sides_follow_the_plan() -> None:
    _, rep = run(gold())
    assert rep.facts["1"]["sides"]["N"] == "left" and rep.facts["1"]["sides"]["S"] == "right"
    # the PDF's eyeline figure: shot 5 Nimal looks screen right, Saman's close-up looks screen left
    assert "looks right" in rep.facts["5"]["eyeline"]
    assert "looks left" in rep.facts["7"]["eyeline"]


def test_side_arithmetic() -> None:
    raw = gold()
    rec = SceneRecord.model_validate(raw)
    w = World(rec)
    a = next(s for s in rec.shots if s.id == "1")
    c = w.cam(a)
    assert w.side(c, a, P(1.0, 0.0)) == "right" and w.side(c, a, P(-1.0, 0.0)) == "left"
    assert w.side(c, a, P(0.0, -5.0)) == "behind"


# ── one break each ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_camera_across_the_line_is_180() -> None:
    raw = gold()
    cam(raw, "B")["y"] = 0.7
    assert "180" in run(raw)[0]


def test_a_reason_makes_a_break_explained() -> None:
    raw = gold()
    cam(raw, "B")["y"] = 0.7
    shot(raw, "2")["breaks"] = [{"rule": "180", "reason": "Saman's world turns over; the cross is the point."}]
    codes, rep = run(raw)
    assert "180" not in codes and any(f.code == "180" for f in rep.by_level("explained"))


def test_same_subject_same_place_is_a_jump_cut() -> None:
    raw = gold()
    s3 = shot(raw, "3")
    s3.update(camera="B", subject="S", type="single", size="MS", in_frame=["S", "N"])
    assert "30_degree" in run(raw)[0]


def test_eyelines_that_do_not_meet() -> None:
    raw = gold()
    shot(raw, "6").update(camera="E", subject="N", type="single", size="MCU", in_frame=["N", "S", "deed"])
    cam(raw, "F").update(x=-0.1, y=0.9)
    codes, _ = run(raw)
    assert {"eyeline", "180"} <= codes


def test_person_left_out_of_a_frame_that_sees_them() -> None:
    raw = gold()
    shot(raw, "2")["in_frame"] = ["S"]
    assert "frame_missing" in run(raw)[0]


def test_person_listed_but_behind_the_camera() -> None:
    raw = gold()
    shot(raw, "7")["in_frame"] = ["S", "N"]
    assert "frame:out" in run(raw)[0]


def test_size_the_lens_cannot_hold() -> None:
    raw = gold()
    shot(raw, "1")["size"] = "MCU"
    assert "size_geometry" in run(raw)[0]


def test_close_up_in_a_calm_beat() -> None:
    raw = gold()
    cam(raw, "B").update(x=-0.2, y=-0.15, lens_mm=85)
    shot(raw, "2").update(size="CU", in_frame=["S"], type="single")
    assert "size_intensity" in run(raw)[0]


def test_peak_that_holds_longer_than_the_calm() -> None:
    raw = gold()
    shot(raw, "7")["duration_s"] = 15
    assert "length_intensity" in run(raw)[0]


def test_broken_chain() -> None:
    raw = gold()
    shot(raw, "3")["start"] = "K1"
    assert "chain:link" in run(raw)[0]


def test_match_on_action_needs_overlap() -> None:
    raw = gold()
    shot(raw, "5")["overlap_in_s"] = 0
    assert "chain:overlap" in run(raw)[0]


def test_prop_before_the_story_shows_it() -> None:
    raw = gold()
    shot(raw, "2")["in_frame"] = ["S", "N", "deed"]
    assert "prop:early" in run(raw)[0]


def test_hand_and_prop_timeline_disagree() -> None:
    raw = gold()
    next(p for p in cut(raw, "K4")["people"] if p["who"] == "N")["right_hand"] = ""
    assert "prop:hand" in run(raw)[0]


def test_invented_clothes() -> None:
    raw = gold()
    shot(raw, "1")["action"] = "Saman, in a mustard blouse, talks over tea."
    assert "wardrobe:invented" in run(raw)[0]
    raw = gold()
    shot(raw, "1")["action"] = "Saman, in a maroon shirt, talks over tea."
    assert "wardrobe:colour" in run(raw)[0]


def test_unknown_person_is_invented_story() -> None:
    raw = gold()
    raw["marks"].append({"id": "M9", "who": "X", "beat": 1, "x": 2, "y": 2, "posture": "standing", "facing": "N",
                         "moves_to": [], "along": ""})
    assert "story:person" in run(raw)[0]


def test_person_in_frame_without_a_mark() -> None:
    raw = gold()
    raw["marks"] = [m for m in raw["marks"] if m["who"] != "S"]
    for k in raw["cuts"]:
        for p in k["people"]:
            if p["who"] == "S":
                p["mark"] = "M1"
    codes, _ = run(raw)
    assert {"place:unmarked", "chain:mark"} <= codes


# ── a walk: screen direction and the path it follows ────────────────────────────────────────────────────────────────
WALK_SCENE = {"blocks": [{"n": 0, "kind": "action", "text": "W walks along the path."}],
              "people": [{"id": "W", "name": "Walker", "look": {"outfit": "A white dress."}, "condition": ""}],
              "props": []}


def walk(second_cam_y: float, to: tuple[float, float] = (10, 0)) -> dict[str, Any]:
    person = {"who": "W", "mark": "M1", "posture": "walking", "left_hand": "", "right_hand": "", "look_at": "",
              "state": ""}
    shots = [{"id": str(i + 1), "beat": 1, "blocks": [0], "purpose": "walk", "type": "single", "camera": c,
              "subject": "W", "in_frame": ["W"], "size": "WS", "angle": "eye", "move": "static", "move_why": "",
              "f_stop": 8, "focus": "W", "start": f"K{i}", "end": f"K{i + 1}", "cut_in": "first" if i == 0 else "cut",
              "overlap_in_s": 0, "overlap_out_s": 0, "duration_s": 4, "action": "W walks.", "lines": [], "breaks": []}
             for i, c in enumerate(("A", "B"))]
    return {"scene": "walk", "dramatic_goal": "", "pov": "W", "objectives": [], "subtext": "",
            "key_moment": {"beat": 1, "what": "the walk", "shots": ["1"]},
            "beats": [{"n": 1, "blocks": [0], "what": "walk", "intensity": 3, "dominant": "W"}],
            "landmarks": [{"id": "path", "name": "path", "kind": "path", "points": [{"x": 0, "y": 0}, {"x": 10, "y": 0}]},
                          {"id": "sky", "name": "sky", "kind": "light", "points": [{"x": 5, "y": 20}]}],
            "marks": [{"id": "M1", "who": "W", "beat": 1, "x": 0, "y": 0, "posture": "walking", "facing": "east",
                       "moves_to": [{"x": to[0], "y": to[1]}], "along": "path"}],
            "axes": [], "light": {"key": "sky", "style": "", "by_beat": [""]}, "prop_states": [],
            "cameras": [{"id": "A", "name": "a", "x": 2, "y": -12, "height": "standing_eye", "looks_at": "W", "lens_mm": 35},
                        {"id": "B", "name": "b", "x": 6, "y": second_cam_y, "height": "standing_eye", "looks_at": "W",
                         "lens_mm": 35}],
            "cuts": [{"id": f"K{i}", "moment": "", "under_way": "", "people": [dict(person, progress=p)]}
                     for i, p in enumerate((0.1, 0.5, 0.9))],
            "shots": shots}


def test_walk_keeps_its_screen_direction() -> None:
    codes, rep = run(walk(-12), WALK_SCENE)
    assert "screen_direction" not in codes, [f.line() for f in rep.faults]
    assert rep.facts["1"]["travel"]["W"] == "to frame right"


def test_walk_flips_when_the_camera_crosses() -> None:
    assert "screen_direction" in run(walk(+12), WALK_SCENE)[0]


def test_walk_off_its_path() -> None:
    assert "move:off_path" in run(walk(-12, to=(0, 10)), WALK_SCENE)[0]


# ── the prompts chain: the end of one clip and the start of the next are the same words ─────────────────────────────
def test_cut_point_words_are_shared() -> None:
    raw = gold()
    rec = SceneRecord.model_validate(raw)
    _, rep = run(raw)
    wr = Writer(rec, SCENE, rep.facts)
    s4, s5 = rec.shots[3], rec.shots[4]
    both = set(s4.in_frame) & set(s5.in_frame)
    for who in ("N", "S"):  # each person on screen on both sides of K4 is the same sentence in both prompts
        assert who in both
        sentence = wr.world_state(wr.w.cuts["K4"], {who}).split(" Under way")[0]
        assert sentence in wr.video_prompt(s4, s5) and sentence in wr.video_prompt(s5, rec.shots[5])
    assert "cups" not in wr.video_prompt(s5, rec.shots[5]).split("KEEP")[0].lower()  # out of frame: not written
    assert "still moving at the last frame" in wr.video_prompt(s4, s5)  # match on action: no settle
    assert "held still" in wr.video_prompt(s5, rec.shots[5])  # a plain cut follows: settle
    assert "mustard" not in wr.frame_brief(s5) and "white sarong" in wr.frame_brief(s5)


def test_close_up_from_behind_the_head() -> None:
    raw = gold()
    cam(raw, "F").update(x=2.2, y=-0.2)  # behind Saman, who looks west at Nimal
    assert "face_hidden" in run(raw)[0]


def test_plan_numbers_in_prompt_words() -> None:
    raw = gold()
    raw["prop_states"][0]["place"] = "on the table at x 0.4, y 0.1"
    assert "words:numbers" in run(raw)[0]


def test_a_camera_for_every_shot_is_too_many_setups() -> None:
    raw = gold()
    for i, s in enumerate(raw["shots"]):  # every shot gets its own new position
        raw["cameras"].append({"id": f"X{i}", "name": "new", "x": -2.5 + i * 0.7, "y": -2.0 - (i % 2),
                               "height": "standing_eye", "looks_at": "table", "lens_mm": 35})
        s["camera"] = f"X{i}"
    assert "setups" in run(raw)[0]


def test_a_shot_takes_its_own_lens_from_its_setup() -> None:
    raw = gold()
    shot(raw, "1")["lens_mm"] = 85  # the master setup, a tighter lens: the plan now reads it tighter
    _, rep = run(raw)
    assert rep.facts["1"]["frame_width_m"] < 1.5


def test_uniform_as_an_adjective_is_not_clothing() -> None:
    raw = gold()
    shot(raw, "1")["action"] = "Cut to a uniform black image while Saman talks."
    assert "wardrobe:invented" not in run(raw)[0]
    shot(raw, "1")["action"] = "Saman, in a school uniform, talks."
    assert "wardrobe:invented" in run(raw)[0]


def test_a_camera_in_the_water_is_noted() -> None:
    raw = gold()
    raw["landmarks"].append({"id": "pond", "name": "pond", "kind": "water",
                             "points": [{"x": -3, "y": -4}, {"x": 3, "y": -4}, {"x": 3, "y": -2.5}, {"x": -3, "y": -2.5}]})
    _, rep = run(raw)
    assert any(f.code == "access:water" and f.level == "advisory" for f in rep.faults)  # camera A at y -3.2
