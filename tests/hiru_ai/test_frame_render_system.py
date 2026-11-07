"""The frame_render system against the legacy pipeline on the cases the Phase 0 fixtures do not reach: look sheets,
frames that wear a look, the vision check. Each scenario runs on both engines over equal fakes and the whole outcome is
compared; the legacy tests of `tests/services/frame_render` say what the right answer is.
"""
from __future__ import annotations

import base64
import copy
from collections.abc import Callable
from dataclasses import replace
from typing import Any
from uuid import uuid4

from frame_render.engine import pipeline as legacy
from frame_render.engine.image import RefusedError

from contracts.producer import Pins
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.ports import ImageRefused
from hiru_ai.systems.frame_render import graph
from tests.parity.graph_support import environment, scripted_models
from tests.parity.harness import seeded_ids
from tests.services.fakes import FakeJobs
from tests.services.frame_render.conftest import FakePainter, FakeStore
from tests.services.frame_render.test_frame_render import add_look, payload, shots
from tests.services.production_fixture import KAMALA

Setup = Callable[[FakeStore], dict[str, Any]]  # prepares the store, returns the payload state


def run_graph(store: FakeStore, p: Any, jobs: FakeJobs, paint: FakePainter | None,
              env: dict[str, str] | None = None, replies: list[Any] | None = None) -> dict[str, Any]:
    class Files:
        def download(self, bucket: str, path: str) -> bytes:
            return store.download_frame(path) if bucket == "frames" else store.download_reference(path)

        def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None:
            store.upload(bucket, path, data, mime)

    def images(prompt: str, aspect: str, references: list[Any], *, draft: bool = False) -> Any:
        try:
            return paint(prompt, aspect, references, draft=draft)  # type: ignore[misc]
        except RefusedError as exc:
            raise ImageRefused(str(exc)) from exc

    ctx = RunContext(production_id=p.production_id, job_id=p.job_id,
                     ports=replace(Ports(), jobs=jobs, scenes=store, frames=store, files=Files(),
                                   images=None if paint is None else images))
    with environment(OPENAI__API_KEY="", **(env or {})):
        if replies is None:
            return graph.run(p, ctx)  # type: ignore[no-any-return]
        with environment(OPENAI__API_KEY="test-key", **(env or {})), \
                scripted_models({"frame_render.vision": replies}, {"vision": "m-vision"}):
            return graph.run(p, ctx)  # type: ignore[no-any-return]


def outcome(store: FakeStore, jobs: FakeJobs, paint: FakePainter | None, result: dict[str, Any]) -> dict[str, Any]:
    copied = copy.deepcopy
    calls = paint.calls if paint else []
    return {"result": result, "status": jobs.status, "events": copied(jobs.events), "frames": copied(store.frame_rows),
            "uploads": {f"{b}/{n}": d for (b, n), d in store.uploads.items()}, "audits": copied(store.audits),
            "assets": copied(store.asset_writes), "looks": copied(store.look_writes),
            "look_rows": copied(store.look_rows),
            "painted": [c["references"] + [c["aspect"], c["prompt"], c["pictures"]] for c in calls],
            "drafts": list(paint.drafts) if paint else []}


def both(setup: Setup, *, orientation: str = "horizontal", painter: dict[str, Any] | None = None,
         replies: list[Any] | None = None, inspect: Any = None) -> dict[str, Any]:
    """Run `setup`'s job on the legacy pipeline and on the graph; they must agree. -> the (graph) outcome."""
    out = []
    for engine in ("legacy", "graph"):
        with seeded_ids():  # the same ids in both runs, so the outcomes compare as they are
            store = FakeStore(orientation=orientation)
            state = setup(store)
            p = payload(**state)
            paint = None if painter is None else FakePainter(**painter)
            jobs = FakeJobs()
            if engine == "legacy":
                result = legacy.run(p, store, jobs, paint, inspect)
            else:
                result = run_graph(store, p, jobs, paint, {"OPENAI__MODEL_VISION": "m-vision"}, replies)
        out.append(_plain(outcome(store, jobs, paint, result)))
    assert out[0] == out[1]
    return out[1]


def _plain(value: dict[str, Any]) -> dict[str, Any]:
    import json

    def blank(node: Any) -> Any:  # the clock differs between two runs
        if isinstance(node, dict):
            return {k: ("<time>" if k == "created_at" else blank(v)) for k, v in node.items()}
        return [blank(v) for v in node] if isinstance(node, list) else node

    return dict(blank(json.loads(json.dumps(
        value, default=lambda b: base64.b64encode(b).decode() if isinstance(b, bytes) else str(b), sort_keys=True))))


def frame_for(store: FakeStore) -> dict[str, Any]:
    return {"frame_ids": [store.add_frame(shots(store)[0]["id"])]}


# ── look sheets ────────────────────────────────────────────────────────────────────────────


def test_a_look_sheet_is_painted_from_the_base_sheet_and_goes_back_to_draft():
    got = both(lambda s: {"look_id": add_look(s)}, orientation="vertical", painter={})
    assert got["result"]["status"] == "done" and got["status"] == "done"
    assert got["painted"][0][1] == "16:9", "a look sheet is wide, even in a vertical production"
    assert got["audits"][0]["action"] == "canon.look_sheet_made"
    assert next(iter(got["look_rows"].values()))["status"] == "draft"


def test_a_look_sheet_without_a_look_or_a_base_sheet_is_reported_not_painted():
    got = both(lambda s: {"look_id": str(uuid4())}, painter={})
    assert "no longer exists" in got["result"]["error"] and not got["painted"]
    got = both(lambda s: {"look_id": add_look(s, entity_id=s.canon_rows[1]["id"])}, painter={})
    assert "base sheet" in got["result"]["error"] and not got["painted"]


def test_an_unreadable_base_sheet_is_a_failure_with_the_safe_message():
    def setup(s: FakeStore) -> dict[str, Any]:
        s.unreadable.add("p/kamala.png")
        return {"look_id": add_look(s)}

    got = both(setup, painter={})
    assert got["result"] == {"status": "failed", "error": graph.FAILED} and not got["looks"]


def test_a_refused_or_failed_look_sheet_leaves_the_old_one_and_a_missing_painter_is_reported():
    refused = both(lambda s: {"look_id": add_look(s)}, painter={"refuse": True})
    assert refused["result"]["status"] == "refused" and not refused["looks"]
    failed = both(lambda s: {"look_id": add_look(s)}, painter={"fail": True})
    assert failed["result"] == {"status": "failed", "error": graph.FAILED}
    none = both(lambda s: {"look_id": add_look(s)}, painter=None)
    assert none["result"] == {"status": "failed", "error": graph.NOT_CONFIGURED}


def test_a_reference_sheet_with_no_card_or_no_painter_or_a_refusal_is_reported():
    for painter, status in (({}, "done"), ({"refuse": True}, "refused"), ({"fail": True}, "failed"),
                            (None, "failed")):
        got = both(lambda s: {"reference_entity_id": s.canon_rows[0]["id"]}, painter=painter)
        assert got["result"]["status"] == status

    def no_card(s: FakeStore) -> dict[str, Any]:
        s.canon_rows[0]["current"] = None
        return {"reference_entity_id": s.canon_rows[0]["id"]}

    assert "no card yet" in both(no_card, painter={})["result"]["error"]


# ── frames wear the look the scene uses ────────────────────────────────────────────────────


def test_the_scenes_pick_dresses_the_person_in_their_look_sheet_not_the_base_sheet():
    def setup(s: FakeStore) -> dict[str, Any]:
        lid = add_look(s)
        s.scene_look_rows = [{"entity_id": KAMALA, "look_id": lid}]
        return frame_for(s)

    got = both(setup, painter={})
    assert got["painted"][0][:2] == ["the look sheet for Kamala", "the location plate for Kamala's house"]
    frame = next(iter(got["frames"].values()))
    assert Pins.model_validate(frame["pins"]).looks[KAMALA].id


def test_without_a_pick_the_narrowest_ready_look_of_the_episode_applies():
    def setup(s: FakeStore) -> dict[str, Any]:
        s.episode = 44
        add_look(s)
        add_look(s, name="Hospital", ranges=[{"from": 44, "to": 44}], outfit="a hospital gown",
                 sheet_assets=[{"path": "hospital.png"}])
        add_look(s, name="Draft", ranges=[{"from": 44, "to": 44}], status="draft", sheet_assets=[{"path": "d.png"}])
        return frame_for(s)

    assert "a hospital gown" in both(setup, painter={})["painted"][0][-2]


def test_an_unreadable_look_sheet_falls_back_to_the_base_sheet_with_the_looks_wardrobe():
    def setup(s: FakeStore) -> dict[str, Any]:
        s.scene_look_rows = [{"entity_id": KAMALA, "look_id": add_look(s)}]
        s.unreadable.add("old.png")
        return frame_for(s)

    got = both(setup, painter={})
    painted = got["painted"][0]
    assert painted[0] == "the character sheet for Kamala" and "outfit maroon silk saree" in painted[-2]


def test_a_shot_that_is_gone_or_a_frame_already_taken_is_handled():
    def gone(s: FakeStore) -> dict[str, Any]:
        fid = s.add_frame(str(uuid4()))
        return {"frame_ids": [fid]}

    got = both(gone, painter={})
    assert got["result"] == {"done": 0, "failed": 1, "refused": 0, "skipped": 0}

    def taken(s: FakeStore) -> dict[str, Any]:
        return {"frame_ids": [s.add_frame(shots(s)[0]["id"], status="running")]}

    assert both(taken, painter={})["result"]["skipped"] == 1


# ── the vision check ───────────────────────────────────────────────────────────────────────


def look(data: bytes, mime: str, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
    """What the legacy inspector hook is, answering the same as the scripted model below."""
    return ANSWER


ANSWER = {"main_people": 3, "unexpected_person": True, "matches": False, "problems": ["the kitchen is missing", "x"]}


def test_the_vision_model_adds_advisory_chips_and_the_frame_is_still_done():
    got = both(frame_for, painter={}, replies=[ANSWER], inspect=look)
    frame = next(iter(got["frames"].values()))
    assert frame["status"] == "done"
    labels = [c["label"] for c in frame["checks"]]
    assert any(label.startswith("3 people in frame") for label in labels) and any(
        label.startswith("Differs") for label in labels)


def test_a_clean_picture_passes_and_a_failed_look_adds_nothing():
    clean = {"main_people": 2, "unexpected_person": False, "matches": True, "problems": []}
    got = both(frame_for, painter={}, replies=[clean], inspect=lambda *a: clean)
    assert any(c["tone"] == "pass" for c in next(iter(got["frames"].values()))["checks"])

    def boom(*args: Any) -> dict[str, Any]:
        raise RuntimeError("vision down")

    # the scripted model has nothing to say (an empty queue raises), as a failing inspector does
    got = both(frame_for, painter={}, replies=[], inspect=boom)
    assert all(c["tone"] != "pass" for c in next(iter(got["frames"].values()))["checks"])


def test_without_a_key_the_frame_is_done_with_no_vision_chips():
    store = FakeStore()
    p = payload(**frame_for(store))
    run_graph(store, p, FakeJobs(), FakePainter(), {"OPENAI__MODEL_VISION": "m-vision"}, None)
    frame = next(iter(store.frame_rows.values()))
    assert frame["status"] == "done" and all("people in frame" not in c["label"] for c in frame["checks"])


def test_with_the_vision_tier_switched_off_there_is_no_vision_call():
    store = FakeStore()
    p = payload(**frame_for(store))
    models = scripted_models({"frame_render.vision": [ANSWER]}, {"vision": "m-vision"})
    with environment(OPENAI__API_KEY="test-key", OPENAI__MODEL_VISION=""), models as recorded:
        ctx = RunContext(production_id=p.production_id, job_id=p.job_id, ports=replace(
            Ports(), jobs=FakeJobs(), scenes=store, frames=store, files=_Files(store), images=FakePainter()))
        graph.run(p, ctx)
    assert recorded.calls == [] and next(iter(store.frame_rows.values()))["status"] == "done"


class _Files:
    def __init__(self, store: FakeStore) -> None:
        self.store = store

    def download(self, bucket: str, path: str) -> bytes:
        return self.store.download_reference(path)

    def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None:
        self.store.upload(bucket, path, data, mime)


# ── draft and final ────────────────────────────────────────────────────────────────────────


def test_a_draft_is_painted_low_and_a_final_from_a_draft_carries_it_first_on_both_engines():
    def setup(store: FakeStore) -> dict[str, Any]:
        shot = shots(store)[0]["id"]
        draft = store.add_draft(shot)
        return {"frame_ids": [store.add_frame(shot, stage="draft"), store.add_frame(shot, draft_id=draft),
                              store.add_frame(shot)]}

    got = both(setup, painter={})
    assert got["drafts"] == [True, False, False]
    from_draft = next(p for p in got["painted"] if "the approved draft of this frame" in p)
    assert from_draft[0] == "the approved draft of this frame"
    assert got["result"]["done"] == 3


def test_an_unreadable_or_foreign_draft_fails_the_final_on_both_engines():
    def setup(store: FakeStore) -> dict[str, Any]:
        shot, other = shots(store)[0]["id"], shots(store)[1]["id"]
        gone = store.add_draft(shot)
        store.unreadable.add(store.frame_rows[gone]["storage_path"])
        foreign = store.add_draft(other)
        return {"frame_ids": [store.add_frame(shot, draft_id=gone), store.add_frame(shot, draft_id=foreign)]}

    got = both(setup, painter={})
    assert got["result"]["failed"] == 2 and got["painted"] == []
