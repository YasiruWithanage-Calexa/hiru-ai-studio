"""video_render engine: claim → generate → store → record, with a fake provider and a fake store (no network).
plan/2026-11-06c Phase 3."""
from __future__ import annotations

import time
from typing import Any

import pytest
from video_render.engine import render
from video_render.engine.transport import ProviderError, RefusedError

from contracts.video_gen import RenderSpec, build_request
from tests.services.video_render.conftest import (
    JPG,
    PID,
    PNG,
    SHOT,
    USER,
    FakeStore,
    config,
    make_spec,
    ref,
    render_row,
)


def run(store: FakeStore, row: dict[str, Any], **cfg: Any) -> str:
    return render.run_render(store, config(**cfg), row, job_id="job-1", actor=str(USER))


class Provider:
    """Stands in for omni/veo: records its calls and answers or raises on cue."""

    RESUMABLE = True

    def __init__(self, raises: Exception | None = None) -> None:
        self.raises, self.calls = raises, []

    def generate(self, built: dict, ref_bytes: dict, **kw: Any) -> dict:
        self.calls.append((built, ref_bytes, kw))
        if self.raises:
            raise self.raises
        if kw.get("on_submitted") and not kw.get("resume_id"):
            kw["on_submitted"]("models/veo/operations/abc")
        return {"data": b"\x00\x00\x00\x18ftypmp42", "mime": "video/mp4", "provider_id": "models/veo/operations/abc",
                "prompt_tokens": 0, "completion_tokens": 0, "provider_seconds": 8}


class Synchronous:
    """Omni's shape: one call, nothing to resume (the real `omni` module has no RESUMABLE)."""

    def __init__(self, inner: Provider) -> None:
        self.generate = inner.generate


@pytest.fixture
def provider(monkeypatch):
    p = Provider()
    monkeypatch.setitem(render.PROVIDERS, "omni_flash", Synchronous(p))
    monkeypatch.setitem(render.PROVIDERS, "veo_3_1", p)
    return p


# ── the happy path ────────────────────────────────────────────────────────────────────────────────────────────


def test_a_render_makes_a_take_and_records_what_was_sent():
    row = render_row()
    store = FakeStore(row)
    assert run(store, row) == "done"

    done = store.rows[row["id"]]
    assert done["status"] == "done" and done["take_id"] and done["error"] is None
    (take,) = store.takes
    assert take["id"] == done["take_id"] == render.take_id_for(row["id"])
    assert take["origin"] == "generated" and take["render_id"] == row["id"] and take["mime"] == "video/mp4"
    assert take["storage_path"] == f"{PID}/{SHOT}/{take['id']}.mp4" and take["uploaded_by"] == str(USER)
    assert take["prompt_version"] == 3 and take["duration_s"] is None
    assert ("takes", take["storage_path"]) in store.uploads
    assert store.usage[0]["phase"] == "video_render.omni_flash" and store.usage[0]["job_id"] == "job-1"

    # the pictures that went are proven by hash, in order
    sent = RenderSpec.model_validate(done["spec"])
    assert [r.source.sha256 != "" for r in sent.references] == [True, True]
    import hashlib

    assert sent.references[0].source.sha256 == hashlib.sha256(PNG).hexdigest()
    assert sent.references[1].source.sha256 == hashlib.sha256(JPG).hexdigest()


def test_each_picture_is_downloaded_once_even_when_bound_twice():
    twice = make_spec([ref("the character sheet for Nimal", f"{PID}/nimal/sheet.png"),
                       ref("Nimal again", f"{PID}/nimal/sheet.png")])
    row = render_row(twice)
    store = FakeStore(row)
    assert run(store, row) == "done"
    assert store.downloads == [("references", f"{PID}/nimal/sheet.png")]


def test_the_provider_gets_pictures_in_the_persons_order_with_their_bytes(provider):
    row = render_row()
    store = FakeStore(row)
    cfg = {"fake_provider": False}
    assert run(store, row, **cfg) == "done"
    built, ref_bytes, kw = provider.calls[0]
    assert [p["path"] for p in built["references"]] == [f"{PID}/nimal/sheet.png", f"{PID}/kitchen/plate.jpg"]
    assert ref_bytes[f"{PID}/nimal/sheet.png"] == (PNG, "image/png")
    assert ref_bytes[f"{PID}/kitchen/plate.jpg"] == (JPG, "image/jpeg")
    assert built["prompt"] == build_request(RenderSpec.model_validate(row["spec"]))["prompt"]
    assert kw["api_key"] == "g" and kw["deadline"] > time.monotonic()


def test_the_deploy_may_choose_a_model_the_person_did_not_but_never_overrides_one_they_chose(provider):
    row = render_row(make_spec([]))
    assert run(FakeStore(row), row, fake_provider=False, models={"omni_flash": "gemini-omni-1.2-flash"}) == "done"
    assert provider.calls[0][0]["model"] == "gemini-omni-1.2-flash"

    chosen = render_row(make_spec([], model="gemini-omni-9"))
    assert run(FakeStore(chosen), chosen, fake_provider=False, models={"omni_flash": "gemini-omni-1.2-flash"}) == "done"
    assert provider.calls[1][0]["model"] == "gemini-omni-9"


def test_veo_seconds_become_the_hidden_usage_equivalent(provider):
    spec = make_spec([], engine="veo_3_1", duration_s=8)
    row = render_row(spec)
    store = FakeStore(row)
    assert run(store, row, fake_provider=False, tokens_per_second={"veo_3_1": 1000}) == "done"
    assert store.usage[0]["output_tokens"] == 8000
    assert store.rows[row["id"]]["usage"]["provider_seconds"] == 8


# ── claim and re-delivery: a video is never paid for twice ─────────────────────────────────────────────────────


def test_a_redelivery_of_a_finished_or_running_render_does_nothing(provider):
    row = render_row()
    store = FakeStore(row)
    assert run(store, row, fake_provider=False) == "done"
    calls = len(provider.calls)
    assert run(store, row, fake_provider=False) == "skipped"  # done
    store.rows[row["id"]]["status"] = "running"
    assert run(store, row, fake_provider=False) == "skipped"  # running, omni cannot resume
    assert len(provider.calls) == calls and len(store.takes) == 1


def test_a_render_that_no_longer_exists_is_skipped():
    row = render_row()
    assert run(FakeStore(), row) == "skipped"


def test_the_provider_id_is_written_the_moment_submit_returns(provider):
    spec = make_spec([], engine="veo_3_1", duration_s=8)
    row = render_row(spec)
    store = FakeStore(row)
    assert run(store, row, fake_provider=False) == "done"
    assert store.rows[row["id"]]["provider_id"] == "models/veo/operations/abc"
    assert provider.calls[0][2]["resume_id"] == ""


def test_resume_polls_the_same_operation_and_downloads_nothing(provider):
    spec = make_spec([], engine="veo_3_1", duration_s=8)
    row = render_row(spec)
    store = FakeStore(row)
    store.rows[row["id"]].update(status="running", provider_id="models/veo/operations/abc",
                                 usage={"submitted_at": time.time() - 4000})
    assert run(store, row, fake_provider=False) == "done"
    assert provider.calls[0][2]["resume_id"] == "models/veo/operations/abc"
    assert provider.calls[0][2]["on_submitted"] is not None
    assert store.downloads == []
    assert store.rows[row["id"]]["usage"]["resumed"] is True


@pytest.mark.parametrize(("engine", "status", "provider_id", "age", "count", "expected"), [
    ("veo_3_1", "running", "op", 4000, 0, "resume"),
    ("veo_3_1", "running", "op", 10, 0, "later"),
    ("veo_3_1", "running", "op#2", 4000, 0, "expire"),
    ("veo_3_1", "running", "", 4000, 0, "skip"),  # never submitted
    ("veo_3_1", "done", "op", 4000, 0, "skip"),
    ("omni_flash", "running", "op", 4000, 0, "skip"),  # synchronous: nothing to resume
])
def test_resume_decisions(engine, status, provider_id, age, count, expected):
    row = render_row(make_spec([], engine=engine, duration_s=8), status=status, provider_id=provider_id,
                     usage={"submitted_at": time.time() - age})
    store = FakeStore(row)
    decision, base = render.resume_claim(store, store.rows[row["id"]], config())
    assert decision == expected
    if expected == "resume":
        assert base == "op" and store.rows[row["id"]]["provider_id"] == "op#1"


def test_two_redeliveries_racing_cannot_both_resume():
    row = render_row(make_spec([], engine="veo_3_1", duration_s=8), status="running", provider_id="op",
                     usage={"submitted_at": time.time() - 4000})
    store = FakeStore(row)
    stale = dict(store.rows[row["id"]])
    assert render.resume_claim(store, stale, config())[0] == "resume"
    assert render.resume_claim(store, stale, config())[0] == "skip"  # the id moved to op#1 under it


def test_an_expired_resume_fails_the_render_for_a_person(provider):
    spec = make_spec([], engine="veo_3_1", duration_s=8)
    row = render_row(spec)
    store = FakeStore(row)
    store.rows[row["id"]].update(status="running", provider_id="op#2", usage={"submitted_at": time.time() - 9999})
    assert run(store, row, fake_provider=False) == "failed"
    assert store.rows[row["id"]]["error"] == render.EXPIRED and provider.calls == []


def test_a_crash_between_storing_and_recording_is_repaired_by_the_retry():
    row = render_row()
    store = FakeStore(row)
    store.duplicate_take = True  # the take row is already there: the same take, same path
    assert run(store, row) == "done"
    assert store.rows[row["id"]]["take_id"] == render.take_id_for(row["id"])


# ── a refusal is a result, a failure is reported in words ──────────────────────────────────────────────────────


def test_a_refusal_is_recorded_and_makes_no_take(provider):
    provider.raises = RefusedError("The model declined to generate this. Try rewording.")
    row = render_row()
    store = FakeStore(row)
    assert run(store, row, fake_provider=False) == "refused"
    got = store.rows[row["id"]]
    assert got["status"] == "refused" and "declined" in got["refusal"] and store.takes == []


def test_a_provider_failure_is_written_for_people_and_names_no_cost(provider):
    provider.raises = ProviderError("the video was still processing when time ran out")
    row = render_row()
    store = FakeStore(row)
    assert run(store, row, fake_provider=False) == "failed"
    error = store.rows[row["id"]]["error"]
    assert error == "The video was still processing when time ran out."
    assert "charge" not in error.lower() and store.takes == []


def test_an_unexpected_exception_never_leaks_its_text(provider):
    provider.raises = RuntimeError("Traceback: key=AIza-secret")
    row = render_row()
    store = FakeStore(row)
    assert run(store, row, fake_provider=False) == "failed"
    assert store.rows[row["id"]]["error"] == render.FAILED


def test_a_network_error_propagates_so_the_handler_can_answer_500(provider):
    import httpx

    provider.raises = httpx.ConnectError("down")
    row = render_row()
    with pytest.raises(httpx.TransportError):
        run(FakeStore(row), row, fake_provider=False)


# ── backstops: what the API checked is checked again ───────────────────────────────────────────────────────────


def test_no_key_says_so_and_calls_nobody(provider):
    row = render_row()
    store = FakeStore(row)
    assert run(store, row, fake_provider=False, google_api_key="") == "failed"
    assert store.rows[row["id"]]["error"] == render.UNAVAILABLE and provider.calls == []


def test_a_picture_outside_this_production_is_refused_and_never_downloaded(provider):
    other = ref("the character sheet for Nimal", "00000000-0000-0000-0000-0000000000a2/nimal/sheet.png")
    row = render_row(make_spec([other]))
    store = FakeStore(row)
    assert run(store, row, fake_provider=False) == "failed"
    assert "not one of this production's" in store.rows[row["id"]]["error"]
    assert store.downloads == [] and provider.calls == []


@pytest.mark.parametrize("path", [f"{PID}/../a2/x.png", f"{PID}//x.png", "x.png"])
def test_path_tricks_are_refused(path, provider):
    row = render_row(make_spec([ref("the character sheet for Nimal", path)]))
    store = FakeStore(row)
    assert run(store, row, fake_provider=False) == "failed"
    assert provider.calls == []


def test_a_request_that_changed_after_it_was_checked_is_refused(provider):
    row = render_row()
    row["request_hash"] = "0" * 64
    store = FakeStore(row)
    assert run(store, row, fake_provider=False) == "failed"
    assert store.rows[row["id"]]["error"] == render.CHANGED and provider.calls == []


def test_a_request_the_engine_cannot_take_is_refused_in_words(provider):
    bad = make_spec([ref("the character sheet for Nimal", f"{PID}/nimal/sheet.png")], engine="veo_3_1", duration_s=6)
    row = render_row(bad)
    store = FakeStore(row)
    assert run(store, row, fake_provider=False) == "failed"
    assert "only at 8 s" in store.rows[row["id"]]["error"] and provider.calls == []


def test_a_spec_that_does_not_parse_is_refused(provider):
    row = render_row()
    row["spec"] = {"engine": "omni_flash"}
    store = FakeStore(row)
    assert run(store, row, fake_provider=False) == "failed"
    assert store.rows[row["id"]]["error"] == render.CHANGED
