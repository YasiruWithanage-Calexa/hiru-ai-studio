"""The Scene board endpoints and the D3 gate on first frames (plan/2026-11-14 §3.3, §3.5). The engine is not run: a
test writes what the board job writes (`paint_done`)."""
from __future__ import annotations

from typing import Any

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
    r = world.client.post(shot_url(world, s, 1, "/frames"), json={}, headers=crew)
    assert r.status_code == 409 and r.json()["detail"] == boards.NO_BOARD
    shot = world.client.get(shot_url(world, s, 1), headers=crew).json()
    assert shot["frame_board"]["state"] == "missing" and not shot["frame_board"]["ready"]
    r = world.client.post(url(world, f"/scenes/{s['scene']['id']}/frames"), json={}, headers=crew)
    assert r.status_code == 409 and "scene board" in r.json()["detail"]
    assert not fired


def test_paint_approve_then_frames_are_painted_from_the_panel(world: World, fired: list[dict]):  # noqa: F811
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    r = world.client.post(board_url(world, s), json={"quality": "medium"}, headers=crew)
    assert r.status_code == 202, r.text
    bid = r.json()["board_id"]
    assert fired[-1]["kind"] == "frame_render" and fired[-1]["state"] == {"board_id": bid, "carry": []}
    assert rows(world)[bid]["quality"] == "medium" and rows(world)[bid]["status"] == "queued"
    again = world.client.post(board_url(world, s), json={}, headers=crew)
    assert again.status_code == 409, "one board at a time"
    assert world.client.post(board_url(world, s), json={"quality": "high"}, headers=crew).status_code == 422, \
        "D2: never high"
    view = world.client.get(board_url(world, s), headers=crew).json()
    assert view["state"] == "painting" and view["job_id"] == r.json()["job_id"]
    assert world.client.post(shot_url(world, s, 1, "/frames"), json={}, headers=crew).json()["detail"] == \
        boards.PAINTING

    paint_done(world, s, bid, ["The bag is white on its sheet and navy in shot 2."])
    view = world.client.get(board_url(world, s), headers=crew).json()
    assert view["state"] == "ready" and view["conflicts"] == ["The bag is white on its sheet and navy in shot 2."]
    cell = view["parts"][0]["cells"][1]
    assert cell["url"].startswith("http") and "/files/" in cell["url"] and "boards" not in cell["url"], \
        "a ticket, never a storage path"
    assert world.client.post(shot_url(world, s, 1, "/frames"), json={}, headers=crew).json()["detail"] == \
        boards.NOT_APPROVED

    view = world.client.post(url(world, f"/scene-boards/{bid}/approve"), headers=crew).json()
    assert view["state"] == "approved" and view["approved"]
    shot = world.client.get(shot_url(world, s, 1), headers=crew).json()
    assert shot["frame_board"]["ready"] and shot["frame_board"]["board_id"] == bid and shot["frame_board"]["panel_url"]
    r = world.client.post(shot_url(world, s, 1, "/frames"), json={}, headers=crew)
    assert r.status_code == 202, r.text
    frame = world.repos.frames.rows[r.json()["frame_ids"][0]]  # type: ignore[attr-defined]
    assert frame["board_id"] == bid and fired[-1]["state"]["from_board"] is True


def test_a_changed_shot_makes_its_panel_out_of_date_and_only_it_is_repainted(world: World,
                                                                             fired: list[dict]):  # noqa: F811
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    bid = world.client.post(board_url(world, s), json={}, headers=crew).json()["board_id"]
    paint_done(world, s, bid)
    world.client.post(url(world, f"/scene-boards/{bid}/approve"), headers=crew)
    shot = world.repos.shots.rows[s["shots"][2]["id"]]  # type: ignore[attr-defined]
    shot["ir"] = {**shot["ir"], "setting": "the kitchen at night"}
    view = world.client.get(board_url(world, s), headers=crew).json()
    assert view["state"] == "stale" and view["changed"] == [3] and not view["whole"]
    assert view["stale_reasons"] == ["shot 3 changed"]
    assert [c["stale"] for c in view["parts"][0]["cells"]] == [False, False, True, False]
    assert world.client.post(shot_url(world, s, 2, "/frames"), json={}, headers=crew).json()["detail"] == boards.STALE
    assert world.client.post(shot_url(world, s, 1, "/frames"), json={}, headers=crew).status_code == 202, \
        "an unchanged shot still paints from its approved panel"

    shot_id = s["shots"][2]["id"]
    v = world.client.patch(url(world, f"/scene-boards/{bid}/cells/{shot_id}"), json={"note": "  side-on,  rain "},
                           headers=crew).json()
    assert v["parts"][0]["cells"][2]["note"] == "side-on, rain"
    r = world.client.post(url(world, f"/scene-boards/{bid}/repaint"), json={}, headers=crew)
    assert r.status_code == 202, r.text
    assert fired[-1]["state"] == {"board_id": bid, "repaint": True, "shots": [3]}
    row = rows(world)[bid]
    assert row["status"] == "queued" and row["approved_at"] is None, "a repaint is approved again"


def test_a_locked_panel_is_never_repainted_and_an_added_shot_needs_a_whole_board(world: World,
                                                                                 fired: list[dict]):  # noqa: F811
    s = open_scene(world)
    design(world, s)
    crew = world.headers(world.crew)
    bid = world.client.post(board_url(world, s), json={}, headers=crew).json()["board_id"]
    paint_done(world, s, bid)
    first = s["shots"][0]["id"]
    world.client.patch(url(world, f"/scene-boards/{bid}/cells/{first}"), json={"locked": True}, headers=crew)
    r = world.client.post(url(world, f"/scene-boards/{bid}/repaint"), json={"shots": [1]}, headers=crew)
    assert r.status_code == 409 and "locked" in r.json()["detail"]
    r = world.client.post(url(world, f"/scene-boards/{bid}/repaint"), json={"shots": [9]}, headers=crew)
    assert r.status_code == 409 and "shot 9" in r.json()["detail"]

    world.repos.shots.rows.pop(s["shots"][3]["id"])  # type: ignore[attr-defined]
    view = world.client.get(board_url(world, s), headers=crew).json()
    assert view["whole"] and view["stale_reasons"] == ["shot 4 removed"]
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
