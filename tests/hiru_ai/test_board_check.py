"""plan/2026-11-23c F2: every painted board panel is looked at (`board_inspector`), and a panel with a fault (a third
arm, a held thing with no hand on it, feet on nothing) is painted again ALONE, once, told what was wrong. Fakes only:
a scripted writer and inspector, a painter that returns a real gridded PNG. Nothing is paid for."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from contracts import board as kit
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.fakes import FakeImages
from hiru_ai.systems.frame_render import graph
from tests.contracts.test_board import board_png
from tests.hiru_ai.test_scene_board import BoardStore, numbers, reply
from tests.parity.graph_support import environment, scripted_models
from tests.services.fakes import FakeJobs
from tests.services.frame_render.test_frame_render import payload

FINE = {"extra_limbs": False, "floating": False, "ungrounded": False, "hands_match": True, "problems": []}
ARM = {**FINE, "extra_limbs": True, "problems": ["red: a third arm holds the pot"]}


def run(store: BoardStore, state: dict[str, Any], writer: list[Any], checks: list[Any],
        painter: FakeImages) -> dict[str, Any]:
    class Files:
        def download(self, bucket: str, path: str) -> bytes:
            return store.download_frame(path) if bucket == "frames" else store.download_reference(path)

        def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None:
            store.upload(bucket, path, data, mime)

    p = payload(**state)
    ctx = RunContext(production_id=p.production_id, job_id=p.job_id,
                     ports=replace(Ports(), jobs=FakeJobs(), scenes=store, frames=store, files=Files(),
                                   images=painter))
    with environment(OPENAI__API_KEY="test-key", OPENAI__MODEL_VISION="m-vision"), \
            scripted_models({"frame_render.board_writer": writer, "frame_render.board_check": checks},
                            {"board": "m-board", "vision": "m-vision"}):
        return graph.run(p, ctx)


def test_a_panel_with_a_fault_is_painted_again_alone_once():
    store = BoardStore()
    bid = store.add_board()
    painter = FakeImages()
    painter.picture = board_png(2, 2)
    shots = numbers(store)
    # the first panel has a third arm, then is fine; every other panel is fine
    checks = [ARM, FINE, *([FINE] * (len(shots) - 1))]
    result = run(store, {"board_id": bid}, [reply(shots)], checks, painter)
    row = store.board_rows[bid]
    assert result["status"] == "done", (result, row.get("error"))
    assert len(painter.calls) == 2, "the board, then the one panel again"
    again = painter.calls[1][0]
    assert "A first painting of this panel was wrong: red: a third arm holds the pot." in again
    assert "ONE photorealistic film still" in again, "painted alone, not as a grid"
    first = next(c for c in row["cells"] if c["number"] == shots[0])
    assert first["check"] == {"ok": True, "problems": [], "fixed": ["red: a third arm holds the pot"],
                              "repainted": True}
    assert first["path"].endswith("-fix.png") and first["source"] == "panel"
    others = [c for c in row["cells"] if c["number"] != shots[0] and c.get("kind") == "painted"]
    assert all(c["check"] == {"ok": True, "problems": []} for c in others)


def test_a_panel_still_wrong_after_its_repaint_is_named_in_the_conflicts():
    store = BoardStore()
    bid = store.add_board()
    painter = FakeImages()
    painter.picture = board_png(2, 2)
    shots = numbers(store)
    checks = [ARM, ARM, *([FINE] * (len(shots) - 1))]
    run(store, {"board_id": bid}, [reply(shots)], checks, painter)
    row = store.board_rows[bid]
    assert len(painter.calls) == 2, "one repaint, never a second"
    assert any(f"Shot {shots[0]}: the board check still sees" in c for c in row["writer"]["conflicts"])


def test_without_the_vision_model_nothing_is_checked_or_repainted():
    store = BoardStore()
    bid = store.add_board()
    painter = FakeImages()
    painter.picture = board_png(2, 2)

    class Files:
        def download(self, bucket: str, path: str) -> bytes:
            return store.download_frame(path) if bucket == "frames" else store.download_reference(path)

        def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None:
            store.upload(bucket, path, data, mime)

    p = payload(board_id=bid)
    ctx = RunContext(production_id=p.production_id, job_id=p.job_id,
                     ports=replace(Ports(), jobs=FakeJobs(), scenes=store, frames=store, files=Files(),
                                   images=painter))
    with environment(OPENAI__API_KEY="test-key", OPENAI__MODEL_VISION=""), \
            scripted_models({"frame_render.board_writer": [reply(numbers(store))]}, {"board": "m-board"}):
        graph.run(p, ctx)
    assert len(painter.calls) == 1
    assert not any("check" in c for c in store.board_rows[bid]["cells"])


def test_the_board_picture_gets_the_place_only_and_paints_props_as_clay():
    store = BoardStore()
    bid = store.add_board()
    painter = FakeImages()
    painter.picture = board_png(2, 2)
    run(store, {"board_id": bid}, [reply(numbers(store))], [FINE] * 10, painter)
    prompt, _, refs = painter.calls[0]
    assert all(not r.label.startswith("the reference sheet for ") for r in refs), "no prop sheet on the board"
    assert "white clay stand-in" in prompt and kit.SUPPORT in prompt


# ── plan/2026-11-24c §2.7: the panel's background is the view it names (lab/final_views fault 1) ────────────────────

REVERSE = "The road and the far side, the frontage out of frame. Wet tarmac."
VIEWS = [{"n": i, "name": n, "camera": f"From the anchor spot, view {i}.", "sees": s, "what": s,
          "box": [0, 0, 500, 330]}
         for i, (n, s) in enumerate([("Wide", "The frontage square on."), ("Looking left", "Along the road."),
                                     ("Looking right", "Along the shops."), ("Reverse", REVERSE),
                                     ("Detail 1", "The drain."), ("Detail 2", "The awning.")], 1)]
WRONG_VIEW = {**FINE, "view_match": False, "problems": ["the background shows the shopfront, not view 4 (Reverse)"]}


def views_store() -> BoardStore:
    from tests.services.production_fixture import HOUSE

    store = BoardStore()
    house = next(c for c in store.canon_rows if c["id"] == HOUSE)
    house["current"] = {**house["current"], "reference_assets": [{"kind": "views", "path": "p/house/views.png",
                                                                  "views": VIEWS}]}
    return store


def test_a_panel_painting_another_view_than_it_names_is_found_and_painted_again_with_the_view_named():
    """The final lab's panels 2 and 3 named view 4 (Reverse) but showed the frontage: the inspector gets the view's
    words and its crop beside the panel, and a mismatch goes the built way (one repaint, told the view)."""
    store = views_store()
    bid = store.add_board()
    painter = FakeImages()
    painter.picture = board_png(2, 2)
    shots = numbers(store)
    answer = reply(shots)
    for p in answer["panels"]:
        p["view"] = 4
    checks = [WRONG_VIEW, FINE, *([FINE] * (len(shots) - 1))]

    class Files:
        def download(self, bucket: str, path: str) -> bytes:
            if bucket == "references" and path == "p/house/views.png":
                return board_png(3, 2)
            return store.download_frame(path) if bucket == "frames" else store.download_reference(path)

        def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None:
            store.upload(bucket, path, data, mime)

    p = payload(board_id=bid)
    ctx = RunContext(production_id=p.production_id, job_id=p.job_id,
                     ports=replace(Ports(), jobs=FakeJobs(), scenes=store, frames=store, files=Files(),
                                   images=painter))
    with environment(OPENAI__API_KEY="test-key", OPENAI__MODEL_VISION="m-vision"), \
            scripted_models({"frame_render.board_writer": [answer], "frame_render.board_check": checks},
                            {"board": "m-board", "vision": "m-vision"}) as recorded:
        result = graph.run(p, ctx)
    assert result["status"] == "done", result
    board_prompt = painter.calls[0][0]
    assert ("Background view: view 4 (Reverse): The road and the far side, the frontage out of frame."
            in board_prompt), "the panel line names the view AND its key words"
    inspect = [c for c, ph in zip(recorded.calls, recorded.phases, strict=True) if ph == "frame_render.board_check"]
    content = inspect[0][-1].content
    text = " ".join(str(x.get("text") or "") for x in content if isinstance(x, dict))
    assert "VIEW: view 4 (Reverse): The road and the far side, the frontage out of frame" in text
    assert sum(1 for x in content if isinstance(x, dict) and x.get("type") in ("image_url", "image")) == 2, \
        "the panel and the view crop beside it"
    again = painter.calls[1][0]
    assert "the background shows the shopfront, not view 4 (Reverse)" in again
    assert "the background is view 4 (Reverse): The road and the far side" in again
    first = next(c for c in store.board_rows[bid]["cells"] if c["number"] == shots[0])
    assert first["check"]["fixed"] == WRONG_VIEW["problems"] and first["check"]["ok"]


def test_a_view_mismatch_alone_is_a_fault():
    from hiru_ai.systems.frame_render.board import _faults

    assert _faults({**FINE, "view_match": False}) == ["the background shows another view of the place than the "
                                                      "panel's"]
    assert _faults(FINE) == [] and _faults({**FINE, "view_match": True}) == []


def test_a_repainted_last_panel_still_carries_into_the_next_part(monkeypatch):
    """2026-11-24 live: the check repainted the last panel of part 1 (its own picture, no box on the sheet), and
    cropping box None failed the part although it was painted and stored. The next part now repeats the repainted
    picture."""
    store = BoardStore()
    bid = store.add_board()
    painter = FakeImages()
    painter.picture = board_png(2, 2)
    shots = numbers(store)
    assert len(shots) == 4
    monkeypatch.setattr(kit, "parts_of", lambda items, aspect=None: [list(items), list(items)[-1:]])
    checks = [FINE, FINE, FINE, ARM, FINE, *([FINE] * 8)]
    run(store, {"board_id": bid}, [reply(shots)], checks, painter)
    first = store.board_rows[bid]
    assert first["status"] == "done", first.get("error")
    last = next(c for c in first["cells"] if c["number"] == shots[-1])
    assert last["check"]["repainted"] and last["box"] is None
    overlap = [r for r in painter.calls[2:] if any(x.label == kit.OVERLAP_LABEL for x in r[2])]
    assert overlap, "part 2 is painted with the repainted last panel of part 1"
