"""The Scene board job and frames painted from a board (plan/2026-11-14 phases 2-4), on the `frame_render` system with
fakes: a scripted board writer, a painter that returns a real gridded PNG, and the frame_render FakeStore with the board
rows added. Nothing is paid for."""
from __future__ import annotations

import io
from dataclasses import replace
from typing import Any
from uuid import uuid4

from PIL import Image

from contracts import board as kit
from contracts.canon import face_sheet_path
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.fakes import FakeImages
from hiru_ai.systems.frame_render import graph
from tests.contracts.test_board import board_png
from tests.parity.graph_support import environment, scripted_models
from tests.services.fakes import FakeJobs
from tests.services.frame_render.conftest import FakeStore
from tests.services.frame_render.test_frame_render import payload, shots
from tests.services.production_fixture import KAMALA, PID


def png(colour: tuple[int, int, int] = (90, 90, 90), size: tuple[int, int] = (1536, 1024)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, format="PNG")
    return buf.getvalue()


class BoardStore(FakeStore):
    """The frame_render FakeStore with `scene_boards` rows and real pictures to crop."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.board_rows: dict[str, dict] = {}
        self.pictures: dict[tuple[str, str], bytes] = {}

    def download_reference(self, path: str) -> bytes:
        if path in self.unreadable:
            raise OSError("gone")
        return png()

    def download_frame(self, path: str) -> bytes:
        if path in self.unreadable:
            raise OSError("gone")
        return self.uploads.get(("frames", path)) or png()

    def add_board(self, **fields: Any) -> str:
        bid = str(uuid4())
        scene_id = next(iter(self.shot_rows.values()))["scene_id"]
        self.board_rows[bid] = {"id": bid, "production_id": str(PID), "scene_id": scene_id, "version": 1, "part": 1,
                                "parts": 1, "status": "queued", "quality": "low", "cells": [], "writer": {},
                                "colours": {}, **fields}
        return bid

    def board(self, board_id: str) -> dict | None:
        row = self.board_rows.get(board_id)
        return dict(row) if row else None

    def boards(self, scene_id: str) -> list[dict]:
        return [dict(r) for r in self.board_rows.values() if r["scene_id"] == scene_id]

    def create_boards(self, rows: list[dict]) -> None:
        for r in rows:
            self.board_rows[r["id"]] = dict(r)

    def claim_board(self, board_id: str) -> bool:
        if self.board_rows[board_id]["status"] != "queued":
            return False
        self.board_rows[board_id]["status"] = "running"
        return True

    def save_board(self, board_id: str, fields: dict) -> None:
        self.board_rows[board_id].update(fields)

    def add_reference_asset(self, version_id: str, assets: list[Any]) -> None:
        super().add_reference_asset(version_id, assets)


def reply(numbers: list[int], name: str = "Kamala") -> dict[str, Any]:
    return {"world": "Dawn light in a kitchen.", "geography": "The stove at screen left, the door at right.",
            "panels": [{"shot": n, "zone": "kitchen", "camera": f"Camera {n}.", "background": "the stove at left",
                        "picture": "The red mannequin stirs a pot.", "people": [{"name": name, "state": ""}]}
                       for n in numbers],
            "conflicts": ["The look says a blue saree; shot 2 says green."]}


def run(store: BoardStore, state: dict[str, Any], replies: list[Any], painter: FakeImages | None) -> tuple[Any, Any]:
    class Files:
        def download(self, bucket: str, path: str) -> bytes:
            return store.download_frame(path) if bucket == "frames" else store.download_reference(path)

        def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None:
            store.upload(bucket, path, data, mime)

    p = payload(**state)
    jobs = FakeJobs()
    ctx = RunContext(production_id=p.production_id, job_id=p.job_id,
                     ports=replace(Ports(), jobs=jobs, scenes=store, frames=store, files=Files(), images=painter))
    with environment(OPENAI__API_KEY="test-key", OPENAI__MODEL_VISION=""), \
            scripted_models({"frame_render.board_writer": replies}, {"board": "m-board"}) as recorded:
        result = graph.run(p, ctx)
    return result, (jobs, recorded)


def numbers(store: BoardStore) -> list[int]:
    return [int(s["number"]) for s in shots(store)]


def test_a_board_is_written_painted_cut_and_stored():
    store = BoardStore()
    bid = store.add_board()
    painter = FakeImages()
    painter.picture = board_png(2, 2)
    result, (_jobs, _recorded) = run(store, {"board_id": bid}, [reply(numbers(store))], painter)
    row = store.board_rows[bid]
    assert result["status"] == "done" and row["status"] == "done", (result, row.get("error"))
    assert painter.qualities[-1] == "low", "D2: a board is painted at the row's quality, LOW by default"
    board_call = painter.calls[-1]
    assert [r.label for r in board_call[2]] == ["the location plate for Kamala's house"], \
        "the board image has no face or look sheet"
    assert "Kamala is the red mannequin" in board_call[0] and "PANEL 4" in board_call[0]
    painted = [c for c in row["cells"] if c["kind"] == "painted"]
    assert [c["number"] for c in painted] == numbers(store) and all(c["path"] and c["box"] for c in painted)
    assert all(c["pin"] == kit.plan_pin(store.shot_rows[c["shot_id"]]) for c in painted)
    assert ("frames", row["sheet_path"]) in store.uploads and ("frames", row["storage_path"]) in store.uploads
    assert row["storage_path"].startswith(f"{PID}/boards/{bid}/")
    assert row["colours"][KAMALA] == "red" and list(row["colours"].values()) == ["red", "blue"]
    assert row["writer"]["conflicts"], "the writer's conflicts are kept for the person"


def test_a_board_makes_the_missing_face_sheets_first_d4():
    store = BoardStore()
    bid = store.add_board()
    painter = FakeImages()
    painter.picture = board_png(2, 2)
    run(store, {"board_id": bid}, [reply(numbers(store))], painter)
    assert painter.qualities[0] == "medium" and painter.sheets[0], "the face sheet first, at MEDIUM"
    kamala = next(c for c in store.canon_rows if c["id"] == KAMALA)
    assert face_sheet_path(kamala).endswith(".png")
    assert store.asset_writes and store.asset_writes[-1][1][0]["kind"] == "face"
    assert any(a.get("path") == "p/kamala.png" for a in store.asset_writes[-1][1]), "the base sheet is kept"


def test_a_writer_that_leaves_out_a_shot_paints_nothing():
    store = BoardStore()
    bid = store.add_board()
    painter = FakeImages()
    result, _ = run(store, {"board_id": bid}, [reply(numbers(store)[:-1])], painter)
    assert result["status"] == "failed" and "left out" in result["error"]
    assert all(not q or q == "medium" for q in painter.qualities), "only the face sheet was painted"


def test_a_board_without_a_painter_or_twice_delivered_is_not_paid_for():
    store = BoardStore()
    bid = store.add_board()
    result, _ = run(store, {"board_id": bid}, [], None)
    assert result["status"] == "failed" and result["error"] == graph.NOT_CONFIGURED
    store.board_rows[bid]["status"] = "done"
    result, _ = run(store, {"board_id": bid}, [], FakeImages())
    assert result["status"] == "skipped"


def test_a_frame_from_the_board_attaches_the_panel_last_and_says_the_mannequins():
    store = BoardStore()
    bid = store.add_board()
    painter = FakeImages()
    painter.picture = board_png(2, 2)
    run(store, {"board_id": bid}, [reply(numbers(store))], painter)
    store.board_rows[bid]["approved_at"] = "2026-11-14T10:00:00Z"
    shot = shots(store)[0]
    fid = store.add_frame(shot["id"], stage="final", board_id=bid)
    painter.picture = png()
    result, _ = run(store, {"frame_ids": [fid], "from_board": True}, [], painter)
    frame = store.frame_rows[fid]
    assert result["done"] == 1, frame.get("error")
    labels = [r.label for r in painter.calls[-1][2]]
    assert labels[0] == "the face sheet for Kamala" and labels[-1] == "the approved draft of this frame"
    assert "Kamala is the red mannequin" in frame["prompt"] and "This shot: Camera 1." in frame["prompt"]
    assert "Kamala stirs a pot." in frame["prompt"]


def test_a_shot_with_a_current_shot_prompt_is_painted_from_it_not_from_the_panel(monkeypatch: Any):
    """The audit of 2026-11-21: the panel says "keep its composition exactly" and was painted before the Camera agent's
    angle and opening; a shot with a current shot prompt is painted from its words and the sheets (lab/shot_prompts)."""
    from hiru_ai.steps.frame_compose import logic

    store = BoardStore()
    bid = store.add_board()
    painter = FakeImages()
    painter.picture = board_png(2, 2)
    run(store, {"board_id": bid}, [reply(numbers(store))], painter)
    store.board_rows[bid]["approved_at"] = "2026-11-14T10:00:00Z"
    record = {"frame": {"composition": "The camera is low at hip height, looking up at Kamala, waist up.",
                        "people": "Kamala stands at the stove, facing left.", "background": "The kitchen.",
                        "light": "Morning light."}, "opening": {"people": [], "background": "", "light": ""}}
    monkeypatch.setattr(logic.World, "shot_prompt_reasons", lambda self, shot: [])
    monkeypatch.setattr(logic.World, "shot_prompt", lambda self, shot: record)
    shot = shots(store)[0]
    fid = store.add_frame(shot["id"], stage="final", board_id=bid)
    painter.picture = png()
    result, _ = run(store, {"frame_ids": [fid], "from_board": True}, [], painter)
    frame = store.frame_rows[fid]
    assert result["done"] == 1, frame.get("error")
    labels = [r.label for r in painter.calls[-1][2]]
    assert "the approved draft of this frame" not in labels and labels[0] == "the face sheet for Kamala"
    assert "This shot: The camera is low at hip height" in frame["prompt"]
    assert "mannequin" not in frame["prompt"] and "keep its composition" not in frame["prompt"]


def test_a_frame_is_painted_at_the_quality_the_person_picked():
    store = BoardStore()
    bid = store.add_board()
    painter = FakeImages()
    painter.picture = board_png(2, 2)
    run(store, {"board_id": bid}, [reply(numbers(store))], painter)
    store.board_rows[bid]["approved_at"] = "2026-11-14T10:00:00Z"
    shot = shots(store)[0]
    painter.picture = png()
    for picked, sent in (("low", "low"), ("medium", "medium"), ("high", ""), (None, "")):
        fid = store.add_frame(shot["id"], stage="final", board_id=bid)
        state: dict[str, Any] = {"frame_ids": [fid], "from_board": True, **({"quality": picked} if picked else {})}
        result, _ = run(store, state, [], painter)
        assert result["done"] == 1, store.frame_rows[fid].get("error")
        assert painter.qualities[-1] == sent, f"{picked!r}: high is never sent; none = the configured quality"


def test_a_frame_whose_board_cannot_be_read_fails_and_is_not_painted():
    store = BoardStore()
    shot = shots(store)[0]
    fid = store.add_frame(shot["id"], stage="final", board_id=str(uuid4()))
    painter = FakeImages()
    result, _ = run(store, {"frame_ids": [fid], "from_board": True}, [], painter)
    assert result["failed"] == 1 and store.frame_rows[fid]["error"] == graph.NO_PANEL
    assert not [q for q in painter.qualities if q != "medium"], "no frame painted (a face sheet may be)"


def test_a_face_sheet_on_request_is_painted_from_the_portrait():
    store = BoardStore()
    painter = FakeImages()
    result, (_jobs, _) = run(store, {"reference_entity_id": KAMALA, "reference_kind": "face"}, [], painter)
    assert result["status"] == "done" and result["kind"] == "face"
    ref = painter.calls[0][2][0]
    assert ref.label == "the portrait of Kamala" and Image.open(io.BytesIO(ref.data)).width < 500
    nimal = next(c for c in store.canon_rows if c["kind"] == "character" and c["id"] != KAMALA)
    result, _ = run(store, {"reference_entity_id": nimal["id"], "reference_kind": "face"}, [], FakeImages())
    assert result["status"] == "failed" and "base sheet first" in result["error"]
