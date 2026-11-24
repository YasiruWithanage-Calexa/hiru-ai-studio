"""plan/2026-11-24: the frame_render job paints a location's views sheet (lab/location_views run_001), writes the views
when nobody edited them, cuts the sheet, and stores it on the location's card. Fakes only: a scripted views writer, a
painter that returns a real 3x2 sheet. Nothing is paid for."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from contracts import canon
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.fakes import FakeImages
from hiru_ai.systems.frame_render import graph
from tests.contracts.test_board import board_png
from tests.hiru_ai.test_scene_board import BoardStore
from tests.parity.graph_support import environment, scripted_models
from tests.services.fakes import FakeJobs
from tests.services.frame_render.test_frame_render import payload
from tests.services.production_fixture import HOUSE

SLOTS = ("Wide from the door", "Opposite wall", "Left wall", "Right wall", "Detail 1", "Detail 2")
ANSWER: dict[str, Any] = {"answers": {"sides": "inside", "moves": False, "size": "room", "why": "a kitchen"},
          "layout": "The kitchen door at left, the hearth at right.", "light": "Smoky morning light.", "empty": [],
          "views": [{"slot": s, "camera": f"From the {s.lower()} spot.", "sees": f"{s} of the kitchen."}
                    for s in SLOTS[:4]]
          + [{"slot": "Detail 1", "camera": "Close on the smoky kitchen hearth.", "sees": "The hearth stones."},
             {"slot": "Detail 2", "camera": "Close on the tiled roof edge.", "sees": "The roof tiles."}]}
# The same answer with a plain table no scene uses as its second detail (lab/place_views r2's restaurant fault).
TABLE: dict[str, Any] = {**ANSWER, "views": [*ANSWER["views"][:5], {
    "slot": "Detail 2", "camera": "Close on a wooden table.", "sees": "A plain table."}]}


def store_with_plate() -> BoardStore:
    store = BoardStore()
    house = next(c for c in store.canon_rows if c["id"] == HOUSE)
    house["current"] = {**house["current"], "id": "house-v1",
                        "reference_assets": [{"kind": "sheet", "path": "p/house/plate.png"}]}
    return store


def run(store: BoardStore, state: dict[str, Any], replies: list[Any], painter: FakeImages) -> dict[str, Any]:
    class Files:
        def download(self, bucket: str, path: str) -> bytes:
            return store.download_frame(path) if bucket == "frames" else store.download_reference(path)

        def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None:
            store.upload(bucket, path, data, mime)

    p = payload(reference_entity_id=HOUSE, reference_kind="views", **state)
    ctx = RunContext(production_id=p.production_id, job_id=p.job_id,
                     ports=replace(Ports(), jobs=FakeJobs(), scenes=store, frames=store, files=Files(),
                                   images=painter))
    with environment(OPENAI__API_KEY="test-key"), \
            scripted_models({"frame_render.views": replies}, {"medium": "m-medium"}) as recorded:
        out = graph.run(p, ctx)
    out["_calls"] = len(recorded.calls)
    return out


def test_the_views_are_written_painted_cut_and_stored_on_the_location():
    store = store_with_plate()
    painter = FakeImages()
    painter.picture = board_png(3, 2)
    out = run(store, {}, [ANSWER], painter)
    assert out["status"] == "done", out
    prompt, aspect, refs = painter.calls[0]
    assert aspect == "16:9" and painter.qualities[-1] == "medium", "the lab's 1536x1024 at medium"
    assert [r.label for r in refs] == ["the location plate for Kamala's house"]
    assert "VIEW 5 (row 2, column 2) — Detail 1: Close on the smoky kitchen hearth. The hearth stones." in prompt
    assert "Light (every view): soft, even, dry daylight" in prompt and "Smoky morning light" not in prompt, \
        "§2.4: the writer's light is kept, never painted"
    version, assets = store.asset_writes[-1]
    sheet = assets[0]
    assert version == "house-v1" and sheet["kind"] == "views" and f"/{HOUSE}/views/house-v1-" in sheet["path"]
    assert [v["name"] for v in sheet["views"]] == list(SLOTS)
    assert sheet["views"][4]["sees"] == "The hearth stones." and sheet["views"][4]["camera"].startswith("Close on")
    assert sheet["views"][4]["what"] == "Close on the smoky kitchen hearth. The hearth stones."
    assert all(len(v["box"]) == 4 for v in sheet["views"]) and sheet["light"] == "Smoky morning light."
    assert sheet["template"] == "inside" and sheet["answers"]["sides"] == "inside" and sheet["findings"] == []
    assert out["_calls"] == 1, "no findings: no re-ask"
    assert assets[1]["path"] == "p/house/plate.png", "the plate is kept"


def test_a_persons_edited_views_are_painted_as_given_with_no_writer_call():
    store = store_with_plate()
    painter = FakeImages()
    painter.picture = board_png(3, 2)
    edited = [{"name": f"View {i}", "what": f"Edited view {i}."} for i in range(1, 7)]
    out = run(store, {"views": edited, "views_layout": {"layout": "Kept.", "light": "Kept light."}}, [], painter)
    assert out["status"] == "done" and out["_calls"] == 0, out
    assert "VIEW 1 (row 1, column 1) — View 1: Edited view 1." in painter.calls[0][0]
    assert store.asset_writes[-1][1][0]["layout"] == "Kept."


def test_a_sheet_that_does_not_cut_into_six_is_never_stored():
    store = store_with_plate()
    painter = FakeImages()
    painter.picture = board_png(2, 2)
    out = run(store, {}, [ANSWER], painter)
    assert out["status"] == "failed" and "different layout" in out["error"]
    assert store.asset_writes == []


def no_plate() -> BoardStore:
    store = BoardStore()
    house = next(c for c in store.canon_rows if c["id"] == HOUSE)
    house["current"] = {**house["current"], "id": "house-v1", "reference_assets": []}
    return store


def test_a_place_without_a_plate_is_painted_from_its_cards_words():
    """plan/2026-11-24c §2.4 (the lab's restaurant and prep room)."""
    store = no_plate()
    painter = FakeImages()
    painter.picture = board_png(3, 2)
    out = run(store, {}, [ANSWER], painter)
    assert out["status"] == "done", out
    prompt, _, refs = painter.calls[0]
    assert refs == [] and "There is no picture of this place: paint it from these words: a small tiled-roof" in prompt


def test_findings_ask_the_writer_once_more_then_store_what_is_left():
    """§2.3 D2: one re-ask with the findings as a list; still failing, stored with the findings shown."""
    store, painter = no_plate(), FakeImages()
    painter.picture = board_png(3, 2)
    out = run(store, {}, [TABLE, ANSWER], painter)
    assert out["status"] == "done" and out["_calls"] == 2 and out["findings"] == [], out
    assert "Close on the tiled roof edge." in painter.calls[0][0], "the second answer is painted"
    store, painter = no_plate(), FakeImages()
    painter.picture = board_png(3, 2)
    out = run(store, {}, [TABLE, TABLE], painter)
    assert out["status"] == "done" and out["_calls"] == 2, out
    assert store.asset_writes[-1][1][0]["findings"] == out["findings"]
    assert out["findings"][0].startswith("Detail 2 (Close on a wooden table) shows nothing the card names")


def test_a_persons_answers_win():
    store, painter = no_plate(), FakeImages()
    painter.picture = board_png(3, 2)
    out = run(store, {"views_answers": {"sides": "inside", "moves": False, "size": "small"}},
              [{**ANSWER, "answers": {"sides": "outside", "moves": False, "size": "long", "why": "w"}}], painter)
    sheet = store.asset_writes[-1][1][0]
    assert sheet["answers"] == {"sides": "inside", "moves": False, "size": "small", "why": "w"}
    assert sheet["template"] == "inside" and out["findings"] == [], "the inside slots match the person's template"


def test_the_views_label_is_what_the_board_attaches():
    assert canon.views_label("Kamala's house").startswith(canon.VIEWS_LABEL_HEAD)


def test_a_frame_gets_its_panels_view_cut_from_the_sheet():
    """plan/2026-11-24 (lab run_003): the location plate is replaced by the panel's view, and the frame is told what
    the view shows."""
    sheet = board_png(3, 2)

    class Files:
        def download(self, bucket: str, path: str) -> bytes:
            assert (bucket, path) == ("references", "p/house/views.png")
            return sheet

    views = [{"n": i, "name": n, "what": f"{n} of the kitchen.", "box": [0, 0, 500, 330]}
             for i, n in enumerate(("Front wide", "Looking left", "Looking right", "Reverse", "Hearth detail",
                                    "Door detail"), 1)]
    house = {"id": HOUSE, "kind": "location", "name": "Kamala's house",
             "current": {"reference_assets": [{"kind": "views", "path": "p/house/views.png", "views": views}]}}
    ctx = RunContext(ports=replace(Ports(), files=Files()))
    world = {"canon": [house], "scene": {"location_id": HOUSE}}
    plate, picture, said = graph._view_picture(ctx, world, 2)  # type: ignore[misc]
    assert plate == "the location plate for Kamala's house"
    assert picture.label == "view 2 (looking left) of the location sheet for Kamala's house"
    assert said == "The background is view 2 (looking left) of the location sheet: Looking left of the kitchen."
    assert graph._view_picture(ctx, world, 0) is None and graph._view_picture(ctx, world, 9) is None
