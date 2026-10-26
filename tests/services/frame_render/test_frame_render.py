"""frame_render: claim → paint → store → record, references in order, refusals, reference sheets."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from frame_render.app.handler import painter
from frame_render.engine import image, pipeline
from frame_render.runtime.config import Config

from contracts.jobs import DispatchPayload, JobKind
from contracts.producer import Pins
from tests.services.fakes import FakeJobs
from tests.services.frame_render.conftest import FakePainter, FakeStore
from tests.services.production_fixture import KAMALA, PID


def payload(**state) -> DispatchPayload:
    return DispatchPayload(job_id=uuid4(), kind=JobKind.FRAME_RENDER, actor_user_id=uuid4(), production_id=PID,
                           pipeline=[JobKind.FRAME_RENDER], state=state)


def shots(store: FakeStore) -> list[dict]:
    return sorted(store.shot_rows.values(), key=lambda s: s["number"])


def test_frames_are_painted_stored_and_pinned():
    store = FakeStore()
    s1, s2 = shots(store)[0], shots(store)[1]
    ids = [store.add_frame(s1["id"]), store.add_frame(s1["id"]), store.add_frame(s2["id"])]
    paint, jobs = FakePainter(), FakeJobs()
    result = pipeline.run(payload(frame_ids=ids), store, jobs, paint)
    assert result == {"done": 3, "failed": 0, "refused": 0, "skipped": 0} and jobs.status == "done"
    f = store.frame_rows[ids[0]]
    assert f["status"] == "done" and f["storage_path"] == f"{PID}/{s1['id']}/{ids[0]}.png"
    assert store.uploads[("frames", f["storage_path"])] == b"\x89PNG fake"
    assert Pins.model_validate(f["pins"]).shot_version == s1["version"]
    # S01's action names Kamala: her sheet first, then the house plate, named by position.
    call = next(c for c in paint.calls if "Kamala" in c["prompt"] and len(c["references"]) == 2)
    assert call["references"] == ["the character sheet for Kamala", "the location plate for Kamala's house"]
    assert "image 1 is the character sheet for Kamala; image 2 is the location plate" in call["prompt"]
    assert f["reference_ids"][0] == KAMALA
    assert "Wide shot, eye level, 28mm lens at f/4" in call["prompt"] and "16:9 framing" in call["prompt"]
    assert store.audits[0]["action"] == "frames.render"


def test_a_redelivery_paints_nothing_twice():
    store = FakeStore()
    fid = store.add_frame(shots(store)[0]["id"])
    paint = FakePainter()
    pipeline.run(payload(frame_ids=[fid]), store, FakeJobs(), paint)
    result = pipeline.run(payload(frame_ids=[fid]), store, FakeJobs(), paint)
    assert result["skipped"] == 1 and len(paint.calls) == 1


def test_a_persons_camera_reaches_the_frame_and_an_unreadable_sheet_is_not_named():
    store = FakeStore(orientation="vertical")
    s1 = shots(store)[0]
    s1["camera_overrides"] = {"framing": "Close-up", "lens": "85mm"}
    store.unreadable.add("p/kamala.png")
    paint = FakePainter()
    pipeline.run(payload(frame_ids=[store.add_frame(s1["id"])]), store, FakeJobs(), paint)
    prompt = paint.calls[0]["prompt"]
    assert "Close-up" in prompt and "85mm" in prompt and "Compose it as a close-up" in prompt
    assert paint.calls[0]["references"] == ["the location plate for Kamala's house"]
    assert "image 1 is the location plate" in prompt and "character sheet" not in prompt
    assert "9:16 vertical framing" in prompt


def test_refusals_failures_and_missing_designs_are_reported_not_raised():
    store = FakeStore()
    s1 = shots(store)[0]
    refused = store.add_frame(s1["id"])
    pipeline.run(payload(frame_ids=[refused]), store, FakeJobs(), FakePainter(refuse=True))
    assert store.frame_rows[refused]["status"] == "refused" and "declined" in store.frame_rows[refused]["error"]

    failed = store.add_frame(s1["id"])
    jobs = FakeJobs()
    pipeline.run(payload(frame_ids=[failed]), store, jobs, FakePainter(fail=True))
    assert store.frame_rows[failed]["status"] == "failed"
    assert "internal" not in store.frame_rows[failed]["error"], "provider text never reaches a person"
    assert jobs.status == "done"

    bare = FakeStore(design=False)
    fid = bare.add_frame(shots(bare)[0]["id"])
    pipeline.run(payload(frame_ids=[fid]), bare, FakeJobs(), FakePainter())
    assert bare.frame_rows[fid]["error"] == pipeline.NO_DESIGN

    off = FakeStore()
    fid = off.add_frame(shots(off)[0]["id"])
    pipeline.run(payload(frame_ids=[fid]), off, FakeJobs(), None)
    assert off.frame_rows[fid]["error"] == pipeline.NOT_CONFIGURED


def test_a_reference_sheet_for_the_current_card():
    store = FakeStore()
    paint, jobs = FakePainter(), FakeJobs()
    result = pipeline.run(payload(reference_entity_id=KAMALA), store, jobs, paint)
    assert result["status"] == "done" and jobs.status == "done"
    assert paint.calls[0]["references"] == [] and "Character reference sheet" in paint.calls[0]["prompt"]
    _, assets = store.asset_writes[0]
    assert assets[0]["path"].startswith(f"{PID}/{KAMALA}/") and assets[1] == {"path": "p/kamala.png"}
    assert ("references", assets[0]["path"]) in store.uploads


def test_the_openai_painter_uses_edit_with_references_and_records_usage():
    sent: dict = {}

    def respond(**kw):
        sent.update(kw)
        return SimpleNamespace(data=[SimpleNamespace(b64_json="iVBORw==")],
                               usage=SimpleNamespace(input_tokens=7, output_tokens=9))

    client = SimpleNamespace(images=SimpleNamespace(edit=respond, generate=respond))
    config = Config("u", "k", "sk", "gpt-image-2", "high", "", "")
    usage: list[dict] = []
    store = SimpleNamespace(record_usage=usage.append)
    paint = painter(config, payload(), store, client)  # type: ignore[arg-type]
    assert paint is not None
    picture = paint("p", "9:16", [image.Reference("a", b"x"), image.Reference("b", b"y")])
    assert sent["size"] == "1024x1536" and [f[0] for f in sent["image"]] == ["reference-1.png", "reference-2.png"]
    assert picture.data.startswith(b"\x89PNG") and usage[0]["output_tokens"] == 9

    class Blocked(Exception):
        code = "moderation_blocked"

    def refuse(**kw):
        raise Blocked("blocked")

    client.images.generate = refuse
    try:
        paint("p", "16:9", [])
        raise AssertionError("expected a refusal")
    except image.RefusedError:
        pass
    assert painter(Config("u", "k", "", "m", "high", "", ""), payload(), store) is None  # type: ignore[arg-type]
