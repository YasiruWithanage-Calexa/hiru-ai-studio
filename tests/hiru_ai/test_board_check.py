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
