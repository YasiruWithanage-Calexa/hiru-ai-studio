"""The two provider modules: the exact request bodies (order, slots, seed) and the resume path, with no network."""
from __future__ import annotations

import base64
from typing import Any

import pytest
from video_render.engine import omni, veo
from video_render.engine.transport import ProviderError, RefusedError

from contracts.video_gen import build_omni_input, build_veo_input
from tests.services.video_render.conftest import make_spec, ref


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


A, B, C, S, E = b"aaa", b"bbb", b"ccc", b"start", b"end"


def pictures():
    refs = [ref("the character sheet for Nimal", "p/a.png"), ref("the location plate for the kitchen", "p/b.png"),
            ref("a red kettle", "p/c.png")]
    bytes_by_path = {"p/a.png": (A, "image/png"), "p/b.png": (B, "image/png"), "p/c.png": (C, "image/png"),
                     "p/s.png": (S, "image/png"), "p/e.png": (E, "image/png")}
    return refs, bytes_by_path


# ── Omni ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_omni_sends_images_in_the_adapters_order_then_the_prompt(monkeypatch):
    refs, files = pictures()
    start, end = ref("the opening frame", "p/s.png", slot="first_frame"), ref("the end", "p/e.png", slot="last_frame")
    built = build_omni_input(make_spec([start, refs[1], end, refs[0], refs[2]]))
    sent: dict[str, Any] = {}

    def post(client: Any, url: str, *, json: dict, timeout: float) -> dict:
        sent.update(url=url, body=json)
        return {}

    monkeypatch.setattr(omni, "_post", post)
    omni.submit(built, files, api_key="KEY", base_url="https://g.test", timeout=30)

    parts = sent["body"]["input"]
    assert [p.get("data") for p in parts[:-1]] == [b64(B), b64(A), b64(C), b64(S), b64(E)]  # refs, start, end
    assert parts[-1] == {"type": "text", "text": built["prompt"]}
    assert "<IMAGE_REF_0> is the location plate for the kitchen." in built["prompt"]
    body = sent["body"]
    assert body["generation_config"]["video_config"]["task"] == "image_to_video"
    assert body["response_format"] == {"type": "video", "aspect_ratio": "16:9", "resolution": "720p",
                                       "duration": "8s", "delivery": "uri"}
    assert sent["url"].startswith("https://g.test/v1beta/interactions?key=KEY") and body["store"] is True


@pytest.mark.parametrize(("slots", "task"), [
    ([], "text_to_video"), (["reference"], "reference_to_video"), (["first_frame"], "image_to_video"),
    (["reference", "last_frame"], "image_to_video")])
def test_omni_task_follows_the_slots(slots, task):
    refs = [ref("a thing", "p/a.png", slot=s) for s in slots]
    assert omni._task(build_omni_input(make_spec(refs))) == task


def test_omni_reads_inline_video_and_the_interaction_id():
    response = {"id": "int-1", "steps": [{"type": "model_output", "content": [
        {"type": "video", "mime_type": "video/mp4", "data": b64(b"clip")}]}],
        "usage": {"total_input_tokens": 120, "total_output_tokens": 900, "total_thought_tokens": 5}}
    out = omni.read_outcome(response)
    assert out["inline"] == b"clip" and out["interaction_id"] == "int-1"
    assert omni.usage_tokens(out["usage"]) == (120, 905)


def test_omni_reads_a_file_uri():
    response = {"outputs": [{"type": "video", "uri": "https://g/v1beta/files/abc123:download"}]}
    assert omni.read_outcome(response)["file_name"] == "files/abc123"


def test_omni_distinguishes_a_refusal_from_a_failure():
    with pytest.raises(RefusedError):
        omni.read_outcome({"steps": [{"type": "model_output", "content": [
            {"type": "text", "text": "I cannot generate this because of a safety policy"}]}]})
    with pytest.raises(ProviderError):
        omni.read_outcome({"status": "failed"})


def test_omni_generate_downloads_when_the_video_is_a_file(monkeypatch):
    refs, files = pictures()
    built = build_omni_input(make_spec(refs[:1]))
    monkeypatch.setattr(omni, "submit", lambda *a, **k: {"id": "i", "outputs": [
        {"type": "video", "uri": "https://g/v1beta/files/zz:download"}], "usage": {"total_input_tokens": 3}})
    seen: list[str] = []
    monkeypatch.setattr(omni, "wait", lambda name, **k: seen.append(f"wait:{name}"))
    monkeypatch.setattr(omni, "download", lambda name, **k: seen.append(f"get:{name}") or b"video")
    out = omni.generate(built, files, api_key="k", base_url="u", deadline=1e12, poll_interval=0, download_attempts=1)
    assert out["data"] == b"video" and out["provider_id"] == "i" and seen == ["wait:files/zz", "get:files/zz"]


# ── Veo ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_veo_body_puts_each_picture_in_its_slot_in_order():
    refs, files = pictures()
    built = build_veo_input(make_spec(refs[:2], engine="veo_3_1", duration_s=8, resolution="1080p"))
    body = veo.build_body(built, files)
    instance, params = body["instances"][0], body["parameters"]
    assert [r["image"]["inlineData"]["data"] for r in instance["referenceImages"]] == [b64(A), b64(B)]
    assert all(r["referenceType"] == "asset" for r in instance["referenceImages"])
    assert "image" not in instance and "lastFrame" not in instance
    assert params == {"aspectRatio": "16:9", "resolution": "1080p", "durationSeconds": 8, "seed": 7}
    assert instance["prompt"].endswith("image 2 is the location plate for the kitchen.")


def test_veo_frames_use_image_and_last_frame():
    _, files = pictures()
    start, end = ref("the opening frame", "p/s.png", slot="first_frame"), ref("the end", "p/e.png", slot="last_frame")
    body = veo.build_body(build_veo_input(make_spec([end, start], engine="veo_3_1", duration_s=8)), files)
    instance = body["instances"][0]
    assert instance["image"]["inlineData"]["data"] == b64(S) and instance["lastFrame"]["inlineData"]["data"] == b64(E)
    assert "referenceImages" not in instance


def test_veo_sends_options_only_when_set_and_no_seed_when_none():
    plain = veo.build_body(build_veo_input(make_spec([], engine="veo_3_1", duration_s=8)), {})
    assert "personGeneration" not in plain["parameters"]
    chosen = veo.build_body(build_veo_input(make_spec([], engine="veo_3_1", duration_s=8,
                                                      options={"person_generation": "allow_all"})), {})
    assert chosen["parameters"]["personGeneration"] == "allow_all"


def test_veo_generate_submits_once_and_reports_the_operation(monkeypatch):
    built = build_veo_input(make_spec([], engine="veo_3_1", duration_s=6))
    calls: list[str] = []
    monkeypatch.setattr(veo, "submit", lambda *a, **k: calls.append("submit") or "models/m/operations/o1")
    monkeypatch.setattr(veo, "poll", lambda op, **k: calls.append(f"poll:{op}") or {"generatedSamples": [
        {"video": {"uri": "https://v/1"}}]})
    monkeypatch.setattr(veo, "download", lambda uri, **k: calls.append(f"get:{uri}") or b"mp4")
    submitted: list[str] = []
    out = veo.generate(built, {}, api_key="k", base_url="u", deadline=1e12, poll_interval=0, download_attempts=1,
                       on_submitted=submitted.append)
    assert submitted == ["models/m/operations/o1"] and calls == ["submit", "poll:models/m/operations/o1", "get:https://v/1"]
    assert out["provider_id"] == "models/m/operations/o1" and out["provider_seconds"] == 6 and out["prompt_tokens"] == 0


def test_veo_resume_never_submits(monkeypatch):
    built = build_veo_input(make_spec([], engine="veo_3_1", duration_s=8))
    monkeypatch.setattr(veo, "submit", lambda *a, **k: pytest.fail("a resumed render must not submit again"))
    monkeypatch.setattr(veo, "poll", lambda op, **k: {"generatedSamples": [{"video": {"uri": f"https://v/{op}"}}]})
    monkeypatch.setattr(veo, "download", lambda uri, **k: uri.encode())
    submitted: list[str] = []
    out = veo.generate(built, {}, api_key="k", base_url="u", deadline=1e12, poll_interval=0, download_attempts=1,
                       on_submitted=submitted.append, resume_id="op-9")
    assert out["data"] == b"https://v/op-9" and submitted == []


def test_veo_video_uri_refusal_and_empty():
    assert veo.video_uri({"generateVideoResponse": {"generatedSamples": [{"video": {"uri": "u"}}]}}) == "u"
    with pytest.raises(RefusedError):
        veo.video_uri({"raiMediaFilteredCount": 1, "raiMediaFilteredReasons": ["blocked"]})
    with pytest.raises(ProviderError):
        veo.video_uri({})


def test_veo_poll_turns_a_safety_error_into_a_refusal(monkeypatch):
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"done": True, "error": {"message": "Blocked by safety filters"}})

    real = httpx.Client
    monkeypatch.setattr(veo.httpx, "Client", lambda **k: real(transport=httpx.MockTransport(handler)))
    with pytest.raises(RefusedError):
        veo.poll("models/m/operations/o", api_key="k", base_url="https://g.test", interval=0, deadline=1e12)


# ── what a person reads when Google answers with an error ──────────────────────────────────────────────────────


def test_a_provider_error_says_what_to_do_and_never_carries_googles_text(monkeypatch: pytest.MonkeyPatch):
    import httpx
    from video_render.engine import transport

    monkeypatch.setattr(transport.time, "sleep", lambda s: None)
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, json={"error": {"message": "Quota exceeded for metric X on project 1234"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(ProviderError) as exc:
        transport.post_json(client, "https://example.test/", json={}, timeout=5)
    assert len(calls) == 4, "a 429 is retried with backoff first"
    said = str(exc.value)
    assert "quota" in said and "(429)" in said and "Google AI Studio" in said
    assert "1234" not in said and exc.value.status == 429
    assert "project 1234" in exc.value.body, "the body is for the log"
    assert transport.status_words(403).startswith("Google refused the API key")
    assert transport.status_words(503) == "The video model had a problem (503). Try again"
    assert transport.status_words(418) == "418 from the video model"


def test_the_fake_provider_makes_a_playable_video():
    """A placeholder a browser can play (found 2026-11-06: 24 header bytes showed a dead player at 0:00)."""
    from video_render.engine import fake

    data = fake.generate({"config": {"duration_seconds": 4}}, {})["data"]
    assert data[4:8] == b"ftyp" and b"moov" in data and b"mdat" in data and b"avc1" in data
    assert 1_000 < len(data) < 50_000, "small enough to keep in the repo"
