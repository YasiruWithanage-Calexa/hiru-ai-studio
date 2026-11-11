"""The Veo 3.1 provider boundary (veo-3.1 / -fast, on the Gemini API key).

Veo is a LONG-RUNNING operation, unlike Omni's single synchronous call:
  submit()   — `POST models/{model}:predictLongRunning` → an operation name. Returns in seconds.
  poll()     — `GET {operation}` until `done`. This is where the minutes go.
  download() — the video URI in the finished operation. Already paid for, so it retries hard.

Request shape from ai.google.dev/gemini-api/docs/veo, checked against the live endpoint with deliberately invalid
values (a 400 costs nothing; `scripts/video_probe.py` maps it for our key):
  instances[0].prompt / .image (start frame) / .lastFrame
  instances[0].referenceImages[{image, referenceType: "asset"}]
  parameters.aspectRatio "9:16"|"16:9", .resolution "720p"|"1080p", .durationSeconds 4|6|8
  parameters.seed, .personGeneration — sent only when the request carries them (Phase 0 settles what the key accepts)

Veo returns NO token counts; it is billed per second of video, so `generate` reports the seconds it rendered
(`provider_seconds`) and zero tokens; the handler turns seconds into the hidden usage equivalent (D3).

RESUMABLE: the operation name is handed to `on_submitted` the moment submit returns, and `generate(resume_id=...)` polls
that operation instead of submitting again, so a re-delivered task never pays for a second video.

Forked from PromptMotion `video_render/engine/veo.py` (see ../../UPSTREAM.md).
"""
from __future__ import annotations

import base64
import logging
import time
from collections.abc import Callable

import httpx

from contracts.safe_depiction import REFUSAL_HINT
from video_render.engine.transport import ProviderError, RefusedError, post_json

_logger = logging.getLogger(__name__)
_REFUSAL_WORDS = ("safety", "policy", "blocked", "filtered", "prohibited")

RESUMABLE = True

# Config keys of `contracts.video_gen` options that map to a `parameters` field of the same meaning.
_OPTION_FIELDS = {"person_generation": "personGeneration"}


def _image(data: bytes, mime: str) -> dict:
    return {"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode("ascii")}}


def build_body(built: dict, ref_bytes: dict[str, tuple[bytes, str]]) -> dict:
    """`contracts.video_gen.build_veo_input`'s output → the predictLongRunning body.

    Each image goes to the slot its `slot` names: a start frame is `image`, an end frame is `lastFrame`, and a
    reference is one entry of `referenceImages`, in the order the prompt numbers them. Nothing is sorted."""
    instance: dict = {"prompt": built["prompt"]}
    refs: list[dict] = []
    for ref in built["references"]:
        data, mime = ref_bytes[ref["path"]]
        if ref["slot"] == "first_frame":
            instance["image"] = _image(data, mime)
        elif ref["slot"] == "last_frame":
            instance["lastFrame"] = _image(data, mime)
        else:
            refs.append({"image": _image(data, mime), "referenceType": "asset"})
    if refs:
        instance["referenceImages"] = refs

    cfg = built["config"]
    parameters: dict = {
        "aspectRatio": cfg["aspect_ratio"],
        "resolution": cfg["resolution"],
        "durationSeconds": int(cfg["duration_seconds"]),
    }
    if cfg.get("seed") is not None:
        parameters["seed"] = int(cfg["seed"])
    if cfg.get("negative_prompt"):
        parameters["negativePrompt"] = cfg["negative_prompt"]
    for key, field in _OPTION_FIELDS.items():
        if key in cfg:
            parameters[field] = cfg[key]
    return {"instances": [instance], "parameters": parameters}


def submit(built: dict, ref_bytes: dict[str, tuple[bytes, str]], *, api_key: str, base_url: str) -> str:
    """Start the generation. Returns the operation name to poll."""
    url = f"{base_url}/v1beta/models/{built['model']}:predictLongRunning?key={api_key}"
    with httpx.Client() as client:
        op = post_json(client, url, json=build_body(built, ref_bytes), timeout=120.0)
    name = op.get("name") or ""
    if not name:
        _logger.warning("veo: no operation name in %s", sorted(op))
        raise ProviderError("the video model did not start the generation")
    return str(name)


def poll(operation: str, *, api_key: str, base_url: str, interval: float, deadline: float) -> dict:
    """Block until the operation is done, then return its `response`.

    `deadline` is an absolute `time.monotonic()` value, so the poll cannot outlive the invocation's budget. A hiccup
    mid-poll is not a failed generation; it is just polled again."""
    url = f"{base_url}/v1beta/{operation}?key={api_key}"
    with httpx.Client() as client:
        while True:
            if time.monotonic() > deadline:
                raise ProviderError("the video was still generating when time ran out")
            try:
                resp = client.get(url, timeout=30.0)
                resp.raise_for_status()
                op = resp.json()
            except httpx.HTTPError:
                op = {}
            if op.get("done"):
                err = op.get("error")
                if err:
                    _logger.warning("veo: operation failed: %s", err)
                    message = str(err.get("message", "")) if isinstance(err, dict) else str(err)
                    if any(w in message.lower() for w in _REFUSAL_WORDS):
                        raise RefusedError(_refusal_text(message))
                    raise ProviderError("the video model could not generate this")
                return dict(op.get("response") or {})
            time.sleep(interval)


def video_uri(response: dict) -> str:
    """The finished video's URI, or a RefusedError when the safety filter removed it."""
    gen = response.get("generateVideoResponse") or response
    samples = gen.get("generatedSamples") or gen.get("generated_samples") or []
    for sample in samples:
        uri = (sample.get("video") or {}).get("uri") or ""
        if uri:
            return str(uri)
    reasons = gen.get("raiMediaFilteredReasons") or []
    if gen.get("raiMediaFilteredCount") or reasons:
        raise RefusedError(_refusal_text(" ".join(str(r) for r in reasons)))
    _logger.warning("veo: no video in response: %s", str(response)[:1000])
    raise ProviderError("the video model returned no video")


def _refusal_text(said: str) -> str:
    """What the person is told. Their prompt or pictures, their problem to fix."""
    detail = f" ({said[:200]})" if said else ""
    return (f"The model declined to generate this{detail}. Try rewording the prompt or using a different picture. "
            f"{REFUSAL_HINT}")  # the hint: plan/2026-11-10b


def download(uri: str, *, api_key: str, attempts: int) -> bytes:
    """Fetch the finished video. It has already cost money, so this retries hard."""
    last: Exception | None = None
    with httpx.Client(follow_redirects=True) as client:
        for attempt in range(max(1, attempts)):
            try:
                resp = client.get(uri, headers={"x-goog-api-key": api_key}, timeout=300.0)
                resp.raise_for_status()
                if resp.content:
                    return resp.content
                last = ProviderError("the finished video was empty")
            except httpx.HTTPError as exc:
                last = exc
            time.sleep(min(2.0 * (attempt + 1), 15.0))
    raise ProviderError("the finished video could not be downloaded") from last


def generate(built: dict, ref_bytes: dict[str, tuple[bytes, str]], *, api_key: str, base_url: str, deadline: float,
             poll_interval: float, download_attempts: int,
             on_submitted: Callable[[str], None] | None = None, resume_id: str = "", **_ignored: object) -> dict:
    """The whole take. Same return shape as `omni.generate`.

    `resume_id`: an operation already submitted for this render; nothing is submitted again, only polled."""
    operation = resume_id or submit(built, ref_bytes, api_key=api_key, base_url=base_url)
    if not resume_id and on_submitted is not None:
        on_submitted(operation)
    response = poll(operation, api_key=api_key, base_url=base_url, interval=poll_interval, deadline=deadline)
    data = download(video_uri(response), api_key=api_key, attempts=download_attempts)
    return {"data": data, "mime": "video/mp4", "provider_id": operation, "prompt_tokens": 0, "completion_tokens": 0,
            "provider_seconds": int(built["config"]["duration_seconds"])}
