"""plan/2026-11-20 D8/D9: a scene planned with its long lines in parts (`scenes.line_parts`). Its shots count the parts
as blocks; the scene view lists, for each shot, the parts it carries, and binds the line to the shot of its first
part."""
from __future__ import annotations

from uuid import uuid4

from contracts import sceneplan
from contracts.shotplan import ProposedShot, fit
from tests.api.conftest import World
from tests.api.test_scenes import url

FATHER = "අනුදි, ඔයා කොහෙද ඉන්නේ? ඉක්මනට ගෙදර එන්න. අපිට ඔයාගේ කසාදෙ ගැන කතා කරන්න තියෙනවා."
ANSWER = "හරි තාත්තේ. මම එන්නම්."


def seed(world: World) -> dict:
    """Anudi's phone rings, her father's long line (three parts), her answer. Shots: the ring, parts 1-2, part 3 and
    the answer."""
    r = world.repos
    pid = str(world.production)
    r.productions.rows[pid]["settings"] = {"max_take_s": 15, "take_lengths": "steps"}  # type: ignore[attr-defined]
    ep = r.episodes.add(production_id=pid, number=1, title="Api Denna", synopsis="", status="ready")  # type: ignore[attr-defined]
    scene = r.scenes.add(production_id=pid, episode_id=ep["id"], number=4, heading="EXT. ROADSIDE", title="",  # type: ignore[attr-defined]
                         note="", time_of_day="DAY", location_id=None, envelope_s=30, status="split", script=[],
                         script_version=1, fit_report={"planner": "raphael"}, line_parts=True)
    lines = [{"id": str(uuid4()), "production_id": pid, "scene_id": scene["id"], "ord": n, "speaker": who,
              "text": text, "delivery": "", "character_id": None}
             for n, (who, text) in enumerate((("Father", FATHER), ("Anudi", ANSWER)))]
    script = [{"kind": "action", "text": "Her phone rings. She answers it.", "line_id": None},
              *({"kind": "dialogue", "text": "", "line_id": ln["id"]} for ln in lines)]
    scene["script"] = script
    items = sceneplan.scene_items(scene, lines)
    lengths = (4, 6, 8, 10, 15)
    assert [(i.part, i.parts) for i in items if i.is_line] == [(1, 3), (2, 3), (3, 3), (0, 0)]
    proposal = [ProposedShot(0, 1, "MS"), ProposedShot(1, 3, "CU"), ProposedShot(3, 5, "MCU")]
    shots, line_rows, _ = sceneplan.rows_after_fit(scene, [{"start": p.start} for p in proposal],
                                                   fit(items, proposal, envelope_s=30, lengths=lengths), lines)
    for s in shots:
        r.shots.rows[s["id"]] = {**s, "created_at": "2026-11-20T00:00:00+00:00"}  # type: ignore[attr-defined]
    for ln in line_rows:
        r.lines.rows[ln["id"]] = ln  # type: ignore[attr-defined]
    return {"scene": scene, "shots": shots, "lines": line_rows}


def test_each_shot_lists_the_parts_it_carries_and_the_line_is_bound_where_it_starts(world: World):
    s = seed(world)
    view = world.client.get(url(world, f"/scenes/{s['scene']['id']}"), headers=world.headers(world.director)).json()
    shots = {x["number"]: x for x in view["shots"]}
    father = s["lines"][0]["id"]
    assert [(p["part"], p["parts"], p["text"]) for p in shots[2]["line_parts"]] == [
        (1, 3, "අනුදි, ඔයා කොහෙද ඉන්නේ?"), (2, 3, "ඉක්මනට ගෙදර එන්න.")]
    assert [(p["part"], p["text"]) for p in shots[3]["line_parts"]] == [(3, "අපිට ඔයාගේ කසාදෙ ගැන කතා කරන්න තියෙනවා.")]
    assert shots[2]["line_ids"] == [father] and shots[3]["line_ids"][0] == father  # one id, however many parts
    line = next(x for x in view["lines"] if x["id"] == father)
    assert line["parts"] == 3 and line["shot_id"] == shots[2]["id"] and line["text"] == FATHER  # the words, whole
    answer = next(x for x in view["lines"] if x["id"] == s["lines"][1]["id"])
    assert answer["parts"] == 0 and answer["shot_id"] == shots[3]["id"]
    assert len(view["script"]) == 3  # the script is three blocks; the father's line is one of them
    assert [b["shot_id"] for b in view["script"]] == [shots[1]["id"], shots[2]["id"], shots[3]["id"]]


def test_a_script_edit_carries_the_shots_across_counting_the_parts(world: World):
    s = seed(world)
    director = world.headers(world.director)
    view = world.client.get(url(world, f"/scenes/{s['scene']['id']}"), headers=director).json()
    blocks = [{"kind": b["kind"], "text": b["text"], "line_id": b["line_id"], "speaker": b["speaker"],
               "delivery": b["delivery"]} for b in view["script"]]
    blocks[2]["text"] = next(x["text"] for x in view["lines"] if x["id"] == blocks[2]["line_id"])
    blocks[1]["text"] = FATHER
    blocks.insert(1, {"kind": "action", "text": "She looks at the screen.", "line_id": None, "speaker": "",
                      "delivery": ""})
    r = world.client.put(url(world, f"/scenes/{s['scene']['id']}/script"),
                         json={"script_version": 1, "blocks": blocks}, headers=world.headers(world.writer))
    assert r.status_code == 200, r.text
    shots = {x["number"]: x for x in r.json()["shots"]}
    assert [p["part"] for x in shots.values() for p in x["line_parts"]] == [1, 2, 3]  # still three parts, in order
