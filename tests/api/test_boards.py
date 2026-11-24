"""The Scene board endpoints and the D3 gate on first frames (plan/2026-11-14 §3.3, §3.5). The engine is not run: a
test writes what the board job writes (`paint_done`)."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from api.services import boards
from contracts.board import plan_pin
from tests.api.conftest import World
from tests.api.test_production import design, fired, open_scene, shot_url  # noqa: F401  (fired is a fixture)
from tests.api.test_scenes import url


@pytest.fixture(autouse=True)
def no_auto_board(world: World) -> None:
    world.repos.scene_boards.auto = False  # type: ignore[attr-defined]


def board_url(world: World, s: dict) -> str:
    return url(world, f"/scenes/{s['scene']['id']}/board")


def scene_frames_url(world: World, s: dict) -> str:
    return url(world, f"/scenes/{s['scene']['id']}/frames")


def rows(world: World) -> dict[str, dict[str, Any]]:
    return world.repos.scene_boards.rows  # type: ignore[attr-defined, no-any-return]


def paint_done(world: World, s: dict, board_id: str, conflicts: list[str] | None = None) -> None:
    """What the board job writes: every shot a painted cell, pinned to the shot as it is now."""
    shots = [world.repos.shots.rows[x["id"]] for x in s["shots"]]  # type: ignore[attr-defined]
    cells = [{"shot_id": r["id"], "number": r["number"], "kind": "painted", "panel": i + 1, "box": [0, 0, 10, 10],
              "path": f"p/boards/{board_id}/cell_{r['number']:03d}.png", "pin": plan_pin(r), "locked": False,
              "note": "", "text": ""} for i, r in enumerate(sorted(shots, key=lambda r: r["number"]))]
    rows(world)[board_id].update(status="done", cells=cells, storage_path=f"p/boards/{board_id}/board.png",
                                 sheet_path=f"p/boards/{board_id}/sheet.png",
                                 writer={"conflicts": conflicts or []})


def test_no_board_no_first_frame_d3(world: World, fired: list[dict]):  # noqa: F811
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    view = world.client.get(board_url(world, s), headers=world.headers(world.reviewer)).json()
    assert view["state"] == "none" and view["parts"] == []
    # plan/2026-11-23d (the person, 2026-11-23): no approved board, no first frame; the button says why
    shot = world.client.get(shot_url(world, s, 1), headers=crew).json()
    assert shot["frame_board"]["state"] == "missing" and not shot["frame_board"]["ready"]
    assert shot["frame_board"]["reason"]
    r = world.client.post(shot_url(world, s, 1, "/frames"), json={}, headers=crew)
    assert r.status_code == 409 and r.json()["detail"] == shot["frame_board"]["reason"]
    assert world.client.post(scene_frames_url(world, s), json={}, headers=crew).status_code == 409


def test_paint_approve_then_frames_are_painted_from_the_panel(world: World, fired: list[dict]):  # noqa: F811
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    r = world.client.post(board_url(world, s), json={"quality": "medium"}, headers=crew)
    assert r.status_code == 202, r.text
    bid = r.json()["board_id"]
    assert fired[-1]["kind"] == "frame_render" and fired[-1]["state"] == {"board_id": bid, "carry": [], "saved": [],
                                                                          "rewrite": True}, "a first board is written"
    assert rows(world)[bid]["quality"] == "medium" and rows(world)[bid]["status"] == "queued"
    again = world.client.post(board_url(world, s), json={}, headers=crew)
    assert again.status_code == 409, "one board at a time"
    assert world.client.post(board_url(world, s), json={"quality": "high"}, headers=crew).status_code == 422, \
        "D2: never high"
    view = world.client.get(board_url(world, s), headers=crew).json()
    assert view["state"] == "painting" and view["job_id"] == r.json()["job_id"]
    assert world.client.post(shot_url(world, s, 1, "/frames"), json={}, headers=crew).status_code == 409, \
        "plan/2026-11-23d: a board being painted draws no first frame"

    paint_done(world, s, bid, ["The bag is white on its sheet and navy in shot 2."])
    view = world.client.get(board_url(world, s), headers=crew).json()
    assert view["state"] == "ready" and view["conflicts"] == ["The bag is white on its sheet and navy in shot 2."]
    cell = view["parts"][0]["cells"][1]
    assert cell["url"].startswith("http") and "/files/" in cell["url"] and "boards" not in cell["url"], \
        "a ticket, never a storage path"
    r = world.client.post(shot_url(world, s, 1, "/frames"), json={}, headers=crew)
    assert r.status_code == 409, "plan/2026-11-23d: an unapproved board draws no first frame"

    view = world.client.post(url(world, f"/scene-boards/{bid}/approve"), headers=crew).json()
    assert view["state"] == "approved" and view["approved"]
    shot = world.client.get(shot_url(world, s, 1), headers=crew).json()
    assert shot["frame_board"]["ready"] and shot["frame_board"]["board_id"] == bid and shot["frame_board"]["panel_url"]
    assert shot["frame_board"]["state"] == "ready"  # plan/2026-11-23d: the approved panel gives the blocking
    r = world.client.post(shot_url(world, s, 1, "/frames"), json={}, headers=crew)
    assert r.status_code == 202, r.text
    frame = world.repos.frames.rows[r.json()["frame_ids"][0]]  # type: ignore[attr-defined]
    assert frame["board_id"] == bid and fired[-1]["state"]["from_board"] is True


def approved_board(world: World, s: dict) -> str:
    crew = world.headers(world.crew)
    bid = world.client.post(board_url(world, s), json={}, headers=crew).json()["board_id"]
    paint_done(world, s, bid)
    world.client.post(url(world, f"/scene-boards/{bid}/approve"), headers=crew)
    return str(bid)


def update_url(world: World, s: dict) -> str:
    return url(world, f"/scenes/{s['scene']['id']}/board/update")


def test_a_changed_shot_is_out_of_date_and_update_board_paints_only_it(world: World,
                                                                       fired: list[dict]):  # noqa: F811
    """plan/2026-11-17 §3.1: one route, one job; every part queued with its approval cleared and carried."""
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    bid = approved_board(world, s)
    approved_at = rows(world)[bid]["approved_at"]
    shot = world.repos.shots.rows[s["shots"][2]["id"]]  # type: ignore[attr-defined]
    shot["ir"] = {**shot["ir"], "setting": "the kitchen at night"}
    view = world.client.get(board_url(world, s), headers=crew).json()
    assert view["state"] == "stale" and view["changed"] == [3] and not view["whole"]
    assert view["stale_reasons"] == ["shot 3 changed"] and view["update"] == [{"number": 3, "what": "changed"}]
    assert [c["stale"] for c in view["parts"][0]["cells"]] == [False, False, True, False]
    r = world.client.post(shot_url(world, s, 2, "/frames"), json={}, headers=crew)
    assert r.status_code == 409, "plan/2026-11-23d: a panel out of date draws no first frame until Update board"
    assert world.client.post(shot_url(world, s, 1, "/frames"), json={}, headers=crew).status_code == 202, \
        "an unchanged shot still paints from its approved panel"

    r = world.client.post(update_url(world, s), json={}, headers=crew)
    assert r.status_code == 202, r.text
    assert r.json()["board_id"] == bid
    state = fired[-1]["state"]
    assert state == {"update": True, "scene_id": s["scene"]["id"], "board_ids": [bid], "shots": [],
                     "approvals": {bid: {"approved_at": approved_at, "approved_by": state["approvals"][bid][
                         "approved_by"]}}}
    row = rows(world)[bid]
    assert row["status"] == "queued" and row["approved_at"] is None and row["job_id"] == r.json()["job_id"]
    assert world.client.get(board_url(world, s), headers=crew).json()["state"] == "painting"
    assert world.client.post(update_url(world, s), json={}, headers=crew).status_code == 409, "one job at a time"
    assert world.repos.audit.entries[-1]["action"] == "board.update"  # type: ignore[attr-defined]
    r = world.client.post(shot_url(world, s, 1, "/frames"), json={}, headers=crew)
    assert r.status_code == 409, "plan/2026-11-23d: a part being updated draws no first frame until it is approved"


def test_added_and_removed_shots_are_listed_for_the_update_not_a_whole_repaint(world: World,
                                                                              fired: list[dict]):  # noqa: F811
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    bid = approved_board(world, s)
    world.repos.shots.rows.pop(s["shots"][3]["id"])  # type: ignore[attr-defined]
    view = world.client.get(board_url(world, s), headers=crew).json()
    assert not view["whole"] and view["stale_reasons"] == ["the board's shot 4 removed"]
    assert view["update"] == [{"number": 4, "what": "removed"}]
    r = world.client.post(update_url(world, s), json={}, headers=crew)
    assert r.status_code == 202, r.text
    assert fired[-1]["state"]["board_ids"] == [bid]


def test_a_locked_panel_is_never_updated_and_nothing_to_do_is_refused(world: World,
                                                                     fired: list[dict]):  # noqa: F811
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    bid = approved_board(world, s)
    r = world.client.post(update_url(world, s), json={}, headers=crew)
    assert r.status_code == 409 and "Nothing on the board is out of date" in r.json()["detail"]
    first = s["shots"][0]["id"]
    world.client.patch(url(world, f"/scene-boards/{bid}/cells/{first}"), json={"locked": True}, headers=crew)
    shot = world.repos.shots.rows[first]  # type: ignore[attr-defined]
    shot["ir"] = {**shot["ir"], "setting": "the yard"}
    view = world.client.get(board_url(world, s), headers=crew).json()
    assert view["update"] == [{"number": 1, "what": "locked"}]
    assert view["stale_reasons"] == ["shot 1 is locked and out of date: unlock to update"]
    r = world.client.post(update_url(world, s), json={}, headers=crew)
    assert r.status_code == 409 and "unlock it" in r.json()["detail"]
    r = world.client.post(update_url(world, s), json={"shots": [first]}, headers=crew)
    assert r.status_code == 409 and "unlock it first" in r.json()["detail"]
    assert world.client.post(update_url(world, s), json={"shots": [str(uuid4())]}, headers=crew).status_code == 404
    assert rows(world)[bid]["approved_at"], "a refused update changes nothing"


def test_update_needs_a_finished_board_in_the_right_shape(world: World, fired: list[dict]):  # noqa: F811
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    r = world.client.post(update_url(world, s), json={}, headers=crew)
    assert r.status_code == 409 and r.json()["detail"] == boards.PAINT_FIRST
    bid = approved_board(world, s)
    rows(world)[bid]["status"] = "failed"
    view = world.client.get(board_url(world, s), headers=crew).json()
    assert view["whole"], "a failed part: only a whole repaint mends it"
    assert world.client.post(update_url(world, s), json={}, headers=crew).json()["detail"] == boards.PAINT_FIRST
    rows(world)[bid].update(status="done", prompt="... Every panel is a tall portrait 9:16 still ...")
    shot = world.repos.shots.rows[s["shots"][1]["id"]]  # type: ignore[attr-defined]
    shot["ir"] = {**shot["ir"], "setting": "the yard"}
    assert world.client.get(board_url(world, s), headers=crew).json()["whole"]
    assert world.client.post(update_url(world, s), json={}, headers=crew).json()["detail"] == boards.WRONG_SHAPE


def test_a_part_that_could_not_be_cut_shows_why_and_asks_for_a_whole_repaint(world: World):
    """plan/2026-11-22 §3.4: the card shows a failed part's error as it is; nothing new in the interface."""
    from hiru_ai.systems.frame_render.board import bad_cut

    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    bid = approved_board(world, s)
    rows(world)[bid].update(status="failed", error=bad_cut([1, 2, 3, 4]), approved_at=None, approved_by=None)
    view = world.client.get(board_url(world, s), headers=crew).json()
    assert view["whole"] and view["state"] == "failed"
    assert view["parts"][0]["error"] == ("Shots 1, 2, 3 and 4 came out in a different layout than was asked. "
                                         "Paint the board again.")


def test_update_waits_while_the_scene_is_planned_and_a_failed_dispatch_keeps_the_approval(
        world: World, fired: list[dict], monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    bid = approved_board(world, s)
    shot = world.repos.shots.rows[s["shots"][1]["id"]]  # type: ignore[attr-defined]
    shot["ir"] = {**shot["ir"], "setting": "the yard"}
    job = str(uuid4())
    world.repos.jobs.rows[job] = {"id": job, "production_id": str(world.production),  # type: ignore[attr-defined]
                                  "kind": "plan_scene_raphael", "status": "running",
                                  "updated_at": "2026-11-17T00:00:00Z"}
    r = world.client.post(update_url(world, s), json={}, headers=crew)
    assert r.status_code == 409 and "being planned" in r.json()["detail"]
    world.repos.jobs.rows[job]["status"] = "done"  # type: ignore[attr-defined]

    async def broken(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("no queue")

    monkeypatch.setattr("api.workers.task_manager.dispatch", broken)
    r = world.client.post(update_url(world, s), json={}, headers=crew)
    assert r.status_code == 503
    row = rows(world)[bid]
    assert row["status"] == "done" and row["approved_at"], "nothing started: the board is back, approved"


def test_the_repaint_route_is_gone(world: World, fired: list[dict]):  # noqa: F811
    s = open_scene(world)
    design(world, s)
    bid = approved_board(world, s)
    r = world.client.post(url(world, f"/scene-boards/{bid}/repaint"), json={}, headers=world.headers(world.crew))
    assert r.status_code in (404, 405), "plan/2026-11-17 D3: the masked repaint is removed"


def test_a_whole_repaint_still_carries_notes_and_locks(world: World, fired: list[dict]):  # noqa: F811
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    bid = approved_board(world, s)
    r = world.client.post(board_url(world, s), json={}, headers=crew)
    assert r.status_code == 202
    assert fired[-1]["state"]["carry"] == [bid], "notes and locks of the current board carry over"
    assert rows(world)[r.json()["board_id"]]["version"] == 2


def test_the_board_is_closed_when_the_scene_is_approved(world: World, fired: list[dict]):  # noqa: F811
    s = open_scene(world)
    s["scene"]["status"] = "approved"
    r = world.client.post(board_url(world, s), json={}, headers=world.headers(world.crew))
    assert r.status_code == 409
    assert world.client.post(board_url(world, s), json={},
                             headers=world.headers(world.reviewer)).status_code == 403


def test_a_face_sheet_is_asked_for_by_canon_editors_and_shown_beside_the_sheet(world: World,
                                                                              fired: list[dict]):  # noqa: F811
    from tests.api.test_canon import add_entity
    from tests.api.test_canon import url as canon_url

    kamala = add_entity(world)
    harbour = add_entity(world, "L01", "Harbour", "location")
    editor = world.headers(world.director)
    r = world.client.post(canon_url(world, kamala, "/face-sheet"), headers=editor)
    assert r.status_code == 409 and "base sheet first" in r.json()["detail"]
    version = world.repos.canon.version_rows[world.repos.canon.rows[kamala]["current_version_id"]]  # type: ignore
    version["reference_assets"] = [{"path": "p/k/face.png", "kind": "face"}, {"path": "p/k/base.png"}]
    r = world.client.post(canon_url(world, kamala, "/face-sheet"), headers=editor)
    assert r.status_code == 202, r.text
    assert fired[-1]["state"] == {"reference_entity_id": kamala, "reference_kind": "face"}
    assert world.client.post(canon_url(world, harbour, "/face-sheet"), headers=editor).status_code == 409
    entity = next(e for e in world.client.get(canon_url(world), headers=editor).json() if e["id"] == kamala)
    assert entity["face_sheet_url"] and entity["reference_sheet_url"] != entity["face_sheet_url"], \
        "the face sheet is never taken for the base sheet"


def test_the_board_view_says_its_shape_and_when_it_is_not_the_productions():
    """2026-11-16: a vertical production paints tall boards; a board painted wide before stays usable, with a note."""
    from uuid import uuid4

    from api.routers.boards import board_view

    sid = uuid4()
    wide = {"id": str(uuid4()), "version": 1, "part": 1, "parts": 1, "status": "done", "cells": [],
            "prompt": "... Every panel is a landscape 16:9 still of the same size ..."}
    tall = dict(wide, prompt="... Every panel is a tall portrait 9:16 still of the same size ...")
    assert board_view(sid, [], [], "9:16").aspect == "9:16", "no board yet: the production's shape"
    old = board_view(sid, [wide], [], "9:16")
    assert old.aspect == "16:9" and old.wrong_shape, "an old wide board on a vertical production"
    new = board_view(sid, [tall], [], "9:16")
    assert new.aspect == "9:16" and not new.wrong_shape
    assert not board_view(sid, [wide], []).wrong_shape, "a wide production's board is right"


def test_the_board_view_names_the_people_on_it_without_a_face_sheet():
    """2026-11-22: nothing paints a face sheet by itself; the board card names who has none, a person makes it."""
    from api.routers.boards import board_view

    ama, nimal, house = (str(uuid4()) for _ in range(3))
    canon = [{"id": ama, "kind": "character", "name": "Ama",
              "current": {"reference_assets": [{"path": "p/a/face.png", "kind": "face"}, {"path": "p/a/base.png"}]}},
             {"id": nimal, "kind": "character", "name": "Nimal",
              "current": {"reference_assets": [{"path": "p/n.png"}]}},
             {"id": house, "kind": "location", "name": "House", "current": {"reference_assets": []}}]
    part = {"id": str(uuid4()), "version": 1, "part": 1, "parts": 1, "status": "done", "cells": [],
            "colours": {ama: "red", nimal: "blue", house: "green"}}
    view = board_view(uuid4(), [part], [], "16:9", canon)
    assert [(str(m.entity_id), m.name) for m in view.missing_faces] == [(nimal, "Nimal")]
    assert board_view(uuid4(), [], [], "16:9", canon).missing_faces == [], "no board: nobody on it yet"


def test_location_views_are_asked_for_on_any_place_and_shown_with_their_names(world: World,
                                                                                       fired: list[dict]):  # noqa: F811
    """plan/2026-11-24: "Make location views" (the views writer writes them) or a person's six edited views;
    plan/2026-11-24c: no plate needed, a person's answers, the template, empty spaces and findings shown."""
    from tests.api.test_canon import add_entity
    from tests.api.test_canon import url as canon_url

    kamala = add_entity(world)
    harbour = add_entity(world, "L01", "Harbour", "location")
    editor = world.headers(world.director)
    assert world.client.post(canon_url(world, kamala, "/views-sheet"), json={}, headers=editor).status_code == 409
    version = world.repos.canon.version_rows[world.repos.canon.rows[harbour]["current_version_id"]]  # type: ignore
    r = world.client.post(canon_url(world, harbour, "/views-sheet"), json={}, headers=editor)
    assert r.status_code == 202, "plan/2026-11-24c §2.4: no plate needed, painted from the card's words"
    state = fired[-1]["state"]
    assert state["reference_kind"] == "views" and "views" not in state and "views_answers" not in state
    assert set(state["views_context"]) == {"within", "comes_and_goes", "geographies", "scenes"}
    answers = {"sides": "both", "moves": False, "size": "room"}
    r = world.client.post(canon_url(world, harbour, "/views-sheet"), json={"answers": answers}, headers=editor)
    assert r.status_code == 202 and fired[-1]["state"]["views_answers"] == answers, "D1: a person's answers"
    assert world.client.post(canon_url(world, harbour, "/views-sheet"), json={"answers": {"sides": "up"}},
                             headers=editor).status_code == 422
    edited = [{"n": i, "name": f"View {i}", "what": f"What {i}."} for i in range(1, 7)]
    r = world.client.post(canon_url(world, harbour, "/views-sheet"), json={"views": edited}, headers=editor)
    assert r.status_code == 202 and fired[-1]["state"]["views"][0] == {"name": "View 1", "what": "What 1.",
                                                                       "camera": "", "sees": ""}
    assert world.client.post(canon_url(world, harbour, "/views-sheet"), json={"views": edited[:3]},
                             headers=editor).status_code == 422, "six views, never fewer"
    version["reference_assets"] = [{"kind": "views", "path": "p/h/views.png", "views": edited, "light": "Rain."},
                                   {"path": "p/h/plate.png"}]
    entity = next(e for e in world.client.get(canon_url(world), headers=editor).json() if e["id"] == harbour)
    assert entity["views_sheet_url"] and entity["reference_sheet_url"] != entity["views_sheet_url"], \
        "the views sheet is never taken for the plate"
    assert [v["name"] for v in entity["views"]][:2] == ["View 1", "View 2"] and entity["views_light"] == "Rain."
    assert entity["views_template"] == "" and entity["views_answers"] is None, "a built sheet has neither"
    version["reference_assets"] = [{"kind": "views", "path": "p/h/views2.png", "template": "both",
                                    "answers": {**answers, "why": "a shop"}, "empty": ["the bay at left, bare"],
                                    "findings": ["Detail 2 is close on a plain table that no scene uses."],
                                    "views": [{"n": 1, "name": "Outside wide", "camera": "From the road.",
                                               "sees": "The front.", "what": "From the road. The front."}]}]
    entity = next(e for e in world.client.get(canon_url(world), headers=editor).json() if e["id"] == harbour)
    assert entity["views_template"] == "both" and entity["views_answers"]["why"] == "a shop"
    assert entity["views_empty"] == ["the bay at left, bare"] and entity["views_findings"][0].startswith("Detail 2")
    assert entity["views"][0] == {"n": 1, "name": "Outside wide", "what": "From the road. The front.",
                                  "camera": "From the road.", "sees": "The front."}


def test_the_views_context_splits_vehicles_out_and_gives_the_scenes_text(world: World):
    """plan/2026-11-24c §2.2: a vehicle named in the place's scenes comes and goes (its space kept empty, never painted
    in); another place named there stands in it; a vehicle's own scenes are those whose words name it."""
    import asyncio
    from uuid import UUID

    from api.routers import canon as canon_router
    from tests.api.test_canon import add_entity

    harbour = add_entity(world, "L01", "Harbour", "location")
    kiosk = add_entity(world, "L02", "Tea kiosk", "location")
    car = add_entity(world, "L03", "Family car", "location")
    rows = world.repos.canon.rows  # type: ignore[attr-defined]
    rows[kiosk]["class"], rows[car]["class"] = "set", "vehicle"
    scene = open_scene(world)["scene"]
    scene["location_id"] = harbour
    scene["script"] = [{"text": "The family car stops beside the tea kiosk."}]
    production = UUID(str(world.production))
    got = asyncio.run(canon_router._views_context(world.repos, production, rows[harbour]))
    assert kiosk in got["within"] and car not in got["within"] and got["comes_and_goes"] == [car]
    assert got["scenes"] == [f"Scene {scene['number']} — {scene.get('heading') or ''}: The family car stops beside "
                             "the tea kiosk."]
    mine = asyncio.run(canon_router._views_context(world.repos, production, rows[car]))
    assert mine["within"] == [] and mine["comes_and_goes"] == [] and len(mine["scenes"]) == 1


def test_a_rejected_part_shows_its_picture_and_why():
    """2026-11-24: a part that failed the cut links its stored picture and the cut drawn on it; never a path."""
    from api.routers.boards import _part_view

    row = {"id": str(uuid4()), "status": "failed", "error": "Part 1 ...", "cells": [], "created_at": "x",
           "checks": [{"kind": "rejected_cut", "problems": ["panel 3: two panels in one crop"],
                       "path": "p/boards/b/rejected.png", "cut_path": "p/boards/b/rejected-cut.png"}]}
    view = _part_view(row, set())
    assert view.rejected_url and "/files/" in view.rejected_url and "rejected" not in view.rejected_url
    assert view.rejected_cut_url and view.rejected_cut_url != view.rejected_url
    assert view.rejected_problems == ["panel 3: two panels in one crop"]
    done = _part_view({**row, "status": "done"}, set())
    assert done.rejected_url is None and done.rejected_problems == []


def test_a_whole_repaint_paints_from_the_saved_words_and_a_changed_shot_asks_for_a_rewrite(
        world: World, fired: list[dict]):  # noqa: F811
    """2026-11-24 (the person): Repaint whole board does not run the board writer; a shot changed since (e.g. in a
    chat) makes "Rewrite and repaint" needed, and a repaint without it is refused."""
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    bid = approved_board(world, s)
    numbers = [c["number"] for c in rows(world)[bid]["cells"]]
    rows(world)[bid]["writer"] = {"world": "w", "geography": "g", "conflicts": [],
                                  "panels": [{"shot": n, "zone": "z", "camera": "c", "background": "b",
                                              "picture": "p", "people": []} for n in numbers]}
    view = world.client.get(board_url(world, s), headers=crew).json()
    assert view["written"] and view["rewrite"] == []
    r = world.client.post(board_url(world, s), json={}, headers=crew)
    assert r.status_code == 202, r.text
    assert fired[-1]["state"]["saved"] == [bid] and fired[-1]["state"]["rewrite"] is False
    rows(world)[r.json()["board_id"]]["status"] = "failed"  # that repaint ended; the words are still bid's

    shot = world.repos.shots.rows[s["shots"][2]["id"]]  # type: ignore[attr-defined]
    shot["ir"] = {**shot["ir"], "setting": "the kitchen at night"}
    assert world.client.get(board_url(world, s), headers=crew).json()["rewrite"] == [3]
    r = world.client.post(board_url(world, s), json={}, headers=crew)
    assert r.status_code == 409 and r.json()["detail"] == ("Shot 3 changed since its panel was written. "
                                                           "Rewrite and repaint, or Update board.")
    r = world.client.post(board_url(world, s), json={"rewrite": True}, headers=crew)
    assert r.status_code == 202 and fired[-1]["state"]["rewrite"] is True


def test_a_painting_board_says_what_its_job_is_doing(world: World, fired: list[dict]):  # noqa: F811
    """2026-11-24: the card shows the job's newest step beside "Painting…"."""
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    r = world.client.post(board_url(world, s), json={}, headers=crew)
    job = r.json()["job_id"]
    assert world.client.get(board_url(world, s), headers=crew).json()["progress"] == ""
    world.repos.jobs.add_event(job, "stage", {"stage": "board", "state": "running", "text": "Writing the panels"})  # type: ignore[attr-defined]
    world.repos.jobs.add_event(job, "stage", {"stage": "board", "state": "running", "text": "Painting part 2 of 3"})  # type: ignore[attr-defined]
    view = world.client.get(board_url(world, s), headers=crew).json()
    assert view["state"] == "painting" and view["progress"] == "Painting part 2 of 3"


def test_approve_board_approves_every_finished_part_at_once(world: World, fired: list[dict]):  # noqa: F811
    """2026-11-24: a person sees one board of shots 1 to N; Approve board approves all its finished parts."""
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    bid = world.client.post(board_url(world, s), json={}, headers=crew).json()["board_id"]
    paint_done(world, s, bid)
    second = {**rows(world)[bid], "id": str(uuid4()), "part": 2, "parts": 2, "approved_at": None}
    rows(world)[bid]["parts"] = 2
    rows(world)[second["id"]] = second
    r = world.client.post(f"{board_url(world, s)}/approve", headers=crew)
    assert r.status_code == 200, r.text
    assert r.json()["approved"] and all(p["approved"] for p in r.json()["parts"])
    assert world.client.post(f"{board_url(world, s)}/approve", headers=crew).status_code == 409, "nothing left"


def with_plate(world: World, s: dict, bid: str) -> None:
    """What the board job writes with fixed marks (plan/2026-11-24d): the spots and one plate over every shot, and the
    scene's staging map holding Kamala still from block 0."""
    shots = sorted((world.repos.shots.rows[x["id"]] for x in s["shots"]),  # type: ignore[attr-defined]
                   key=lambda r: r["number"])
    numbers = [r["number"] for r in shots]
    rows(world)[bid]["writer"] = {
        "world": "w", "geography": "g", "conflicts": [],
        "panels": [{"shot": n, "zone": "z", "camera": "c", "background": "b", "picture": "p", "people": []}
                   for n in numbers],
        "marks": [{"stretch": 1, "who": "Kamala", "spot": "on the kitchen floor, one step right of the stove",
                   "apart": ""}],
        "plates": [{"n": 1, "shots": numbers, "shot_ids": [r["id"] for r in shots], "people": ["Kamala"],
                    "path": f"p/boards/{bid}/plate_1-abcd1234.png", "pin": "x", "prompt": "secret words",
                    "check": {"ok": False, "problems": ["red: a held thing with no hand on it"]}}]}
    world.repos.scenes.rows[s["scene"]["id"]]["staging"] = {  # type: ignore[attr-defined]
        "by": "model", "marks": [{"block": 0, "who": "Kamala", "zone": "kitchen", "posture": "standing"}]}


def test_the_plate_is_internal_and_only_its_changed_marks_are_said(world: World,
                                                                  fired: list[dict]):  # noqa: F811
    """The person, 2026-11-25: the blocking plate is generated and kept on the backend, never shown."""
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    bid = approved_board(world, s)
    with_plate(world, s, bid)
    view = world.client.get(board_url(world, s), headers=crew).json()
    assert "plates" not in view and view["state"] == "approved" and view["stale_reasons"] == []
    text = str(view)
    assert "plate_1" not in text and "secret words" not in text and "kitchen floor" not in text, \
        "no plate, ticket, prompt or spot reaches a browser"

    world.repos.scenes.rows[s["scene"]["id"]]["staging"]["marks"].append(  # type: ignore[attr-defined]
        {"block": 2, "who": "Kamala", "zone": "kitchen", "posture": "walking"})
    view = world.client.get(board_url(world, s), headers=crew).json()
    assert any(r.startswith("The marks of shots 1") for r in view["stale_reasons"])


def test_repaint_marks_paints_the_plate_again_as_a_repaint(world: World, fired: list[dict]):  # noqa: F811
    """D3: the plate and then the parts, from the saved words (no board writer), at the board's quality."""
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    bid = approved_board(world, s)
    with_plate(world, s, bid)
    plate_url = url(world, f"/scenes/{s['scene']['id']}/board/plates/1/repaint")
    r = world.client.post(plate_url, headers=crew)
    assert r.status_code == 202, r.text
    state = fired[-1]["state"]
    assert state["repaint_plates"] == [1] and state["rewrite"] is False and state["saved"] == [bid]
    assert rows(world)[r.json()["board_id"]]["version"] == 2
    rows(world)[r.json()["board_id"]]["status"] = "failed"
    missing = url(world, f"/scenes/{s['scene']['id']}/board/plates/9/repaint")
    assert world.client.post(missing, headers=crew).status_code == 404
    assert world.client.post(plate_url, headers=world.headers(world.reviewer)).status_code == 403


def test_a_board_written_before_fixed_marks_asks_for_a_rewrite(world: World, fired: list[dict]):  # noqa: F811
    """plan/2026-11-24d: the words have no spots while the staging map holds someone still over two shots."""
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    bid = approved_board(world, s)
    with_plate(world, s, bid)
    assert not world.client.get(board_url(world, s), headers=crew).json()["marks_needed"]
    rows(world)[bid]["writer"].pop("marks")
    rows(world)[bid]["writer"].pop("plates")
    assert world.client.get(board_url(world, s), headers=crew).json()["marks_needed"]
    world.repos.scenes.rows[s["scene"]["id"]]["staging"] = {}  # type: ignore[attr-defined]
    assert not world.client.get(board_url(world, s), headers=crew).json()["marks_needed"], "no map, nothing to hold"

