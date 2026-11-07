"""The provider boundary: everything that knows how Gemini Omni is actually called.

ONE FILE, on purpose. Adding a second video model means a sibling of this module plus one entry
in `contracts.video_gen.ENGINE_CAPABILITIES` / `ADAPTERS` and one in `render.PROVIDERS`. No other file
learns a provider's name. Forked from PromptMotion (see ../../UPSTREAM.md).

Omni is served ONLY by the Interactions API (`POST /v1beta/interactions`). `generateContent`
answers 400 "This model only supports Interactions API" — which is why the first S0 probe, run
against that endpoint, mapped a schema that does not apply to this model. The request shape
below was checked field by field against the live endpoint on 2026-09-24 (unknown fields are
rejected by name, so a 400 is a free schema oracle):

  response_format.type          "video"
  response_format.aspect_ratio  "9:16" | "16:9"            (nothing else)
  response_format.resolution    "360p" | "720p" | "1080p" | "4k"
  response_format.duration      "<n>s"  (a protobuf Duration STRING; a bare number is rejected)
  response_format.delivery      "uri" | "base64"   (base64 caps at ~4MB, so uri is normal)
  generation_config.video_config.task
                                text_to_video | image_to_video | reference_to_video | edit | extend

Three steps, kept separate because they fail differently:
  submit()  — one POST. Rate limits and refusals surface here.
  wait()    — the Files API poll, for a `uri` delivery.
  download()— the bytes. Already paid for by this point, so it retries hard.
"""
from __future__ import annotations

import base64
import logging
import re
import time

import httpx

from video_render.engine.transport import ProviderError, RefusedError
from video_render.engine.transport import post_json as _post

_logger = logging.getLogger(__name__)

# Words a declined generation's explanation tends to carry. Used only to tell a refusal (a
# RESULT: reported, charged nothing, never retried) from a plain provider failure.
_REFUSAL_HINTS = ("safety", "policy", "prohibited", "blocked", "cannot generate",
                  "can't generate", "unable to generate", "not able to generate", "recitation")

__all__ = [
    "ProviderError",
    "RefusedError",
    "download",
    "generate",
    "read_outcome",
    "submit",
    "usage_tokens",
    "wait",
]


def _task(built: dict) -> str:
    """Which video task the request is. Frames make it image-to-video (one image animates from
    that frame; two interpolate first → last); plain references make it reference-to-video."""
    roles = {r["slot"] for r in built["references"]}
    if roles & {"first_frame", "last_frame"}:
        return "image_to_video"
    if roles:
        return "reference_to_video"
    return "text_to_video"


def submit(built: dict, ref_bytes: dict[str, tuple[bytes, str]], *, api_key: str,
           base_url: str, timeout: float) -> dict:
    """Send one generation and wait for it (synchronous: `background=false`).

    `built` is `contracts.video_gen.build_omni_input`'s output. `ref_bytes` maps a reference PATH to
    its (bytes, mime) — downloaded by the caller from the private bucket, because this module
    must not know what a bucket is.

    The images are sent IN THE ORDER the adapter listed them, which is the order its
    `<IMAGE_REF_n>` tags count in (and, for frames, first before last — the order the model
    interpolates in). Sorting or de-duplicating them here would silently renumber every
    citation in the prompt.
    """
    parts: list[dict] = []
    for ref in built["references"]:
        data, mime = ref_bytes[ref["path"]]
        parts.append({"type": "image", "mime_type": mime,
                      "data": base64.b64encode(data).decode("ascii")})
    parts.append({"type": "text", "text": built["prompt"]})

    cfg = built["config"]
    body = {
        "model": built["model"],
        "input": parts,
        "background": False,
        # Stored so `interaction_id` can drive a later edit/extend turn
        # (`previous_interaction_id`). Phase 5 cannot be retrofitted onto unstored takes.
        "store": True,
        "generation_config": {"video_config": {"task": _task(built)}},
        "response_format": {
            "type": "video",
            "aspect_ratio": cfg["aspect_ratio"],
            "resolution": cfg["resolution"],
            "duration": f"{int(cfg['duration_seconds'])}s",
            "delivery": "uri",
        },
    }
    url = f"{base_url}/v1beta/interactions?key={api_key}"
    with httpx.Client() as client:
        return _post(client, url, json=body, timeout=timeout)


def _output_items(response: dict) -> list[dict]:
    """Every content item the model produced. The documented shape is `steps[]` with a
    `model_output` step; `outputs[]` is read too because the API reference also describes it,
    and missing the video here would fail a take that was already paid for."""
    items: list[dict] = []
    for step in response.get("steps") or []:
        if (step.get("type") or "") == "model_output":
            items.extend(step.get("content") or [])
    items.extend(response.get("outputs") or [])
    return items


_FILE_NAME = re.compile(r"(files/[^/:?]+)")


def read_outcome(response: dict) -> dict:
    """Pull the take's result out of the response, without fetching anything.

    Returns `{"file_name": str, "inline": bytes|None, "mime": str, "interaction_id": str,
    "usage": dict}`. Raises `RefusedError` when the model declined.
    """
    status = (response.get("status") or "").lower()
    items = _output_items(response)

    file_name, inline, mime = "", None, "video/mp4"
    texts: list[str] = []
    for item in items:
        item_type = (item.get("type") or "").lower()
        if item_type == "video":
            mime = item.get("mime_type") or item.get("mimeType") or mime
            if item.get("data"):
                inline = base64.b64decode(item["data"])
            elif item.get("uri"):
                m = _FILE_NAME.search(item["uri"])
                file_name = m.group(1) if m else ""
        elif item_type == "text" and item.get("text"):
            texts.append(item["text"])

    if not file_name and inline is None:
        _logger.warning("omni: no video in response: status=%r keys=%s texts=%r error=%r", status,
                        sorted(response), texts[:2], response.get("error"))
        said = " ".join(texts).strip()
        error = response.get("error") or {}
        reason = f"{said} {error.get('message', '') if isinstance(error, dict) else error}"
        if any(h in reason.lower() for h in _REFUSAL_HINTS):
            raise RefusedError(_refusal_text(said))
        raise ProviderError("the video model returned no video")

    return {
        "file_name": file_name,
        "inline": inline,
        "mime": mime,
        # Stored on every take FROM DAY ONE. Phase 5's extend/edit paths cannot be retrofitted
        # onto takes generated without it.
        "interaction_id": response.get("id") or "",
        "usage": response.get("usage") or {},
    }


def _refusal_text(said: str) -> str:
    """What the user is told. Their prompt, their problem to fix."""
    detail = f" ({said[:200]})" if said else ""
    return (f"The model declined to generate this{detail}. "
            f"Try rewording the prompt or removing a reference picture.")


def wait(file_name: str, *, api_key: str, base_url: str, interval: float,
         deadline: float) -> None:
    """Block until the generated file is ACTIVE, or raise.

    `deadline` is an absolute `time.monotonic()` value, not a duration, so the poll cannot
    outlive the invocation's own budget no matter how long submit() took.
    """
    url = f"{base_url}/v1beta/{file_name}?key={api_key}"
    with httpx.Client() as client:
        while True:
            if time.monotonic() > deadline:
                raise ProviderError("the video was still processing when time ran out")
            try:
                resp = client.get(url, timeout=30.0)
                resp.raise_for_status()
                state = (resp.json().get("state") or "").upper()
            except httpx.HTTPError:
                state = ""            # a hiccup mid-poll is not a failed generation
            if state == "ACTIVE":
                return
            if state == "FAILED":
                raise ProviderError("the video model failed while processing the result")
            time.sleep(interval)


def download(file_name: str, *, api_key: str, base_url: str, attempts: int) -> bytes:
    """Fetch the finished video.

    By this point the generation has SUCCEEDED and has already cost real money, so this retries
    hard rather than failing the take: "a failed take is never charged" is only an honest promise
    if a retrieval hiccup costs latency instead of the video.
    """
    url = f"{base_url}/v1beta/{file_name}:download?alt=media&key={api_key}"
    last: Exception | None = None
    with httpx.Client(follow_redirects=True) as client:
        for attempt in range(max(1, attempts)):
            try:
                resp = client.get(url, timeout=300.0)
                resp.raise_for_status()
                if resp.content:
                    return resp.content
                last = ProviderError("the finished video was empty")
            except httpx.HTTPError as exc:
                last = exc
            time.sleep(min(2.0 * (attempt + 1), 15.0))
    raise ProviderError("the finished video could not be downloaded") from last


def usage_tokens(usage: dict) -> tuple[int, int]:
    """(prompt_tokens, completion_tokens) from the Interaction's `usage` object.

    The completion side is the VIDEO — frames billed as output tokens — which is where ~99% of
    the money is. Thinking bills at the output rate, so it is counted on that side too. The
    generateContent spellings are still read as a fallback: a missed key here reads as a free
    take.
    """
    prompt = (usage.get("total_input_tokens") or usage.get("promptTokenCount")
              or usage.get("prompt_token_count") or 0)
    completion = ((usage.get("total_output_tokens") or 0) + (usage.get("total_thought_tokens") or 0)
                  or usage.get("candidatesTokenCount") or usage.get("candidates_token_count") or 0)
    if not completion:
        total = usage.get("total_tokens") or usage.get("totalTokenCount") or 0
        completion = max(0, total - prompt)
    return int(prompt), int(completion)


def generate(built: dict, ref_bytes: dict[str, tuple[bytes, str]], *, api_key: str,
             base_url: str, deadline: float, poll_interval: float,
             download_attempts: int, **_ignored: object) -> dict:
    """The whole take: submit, then fetch the video however it was delivered.

    Returns `{"data": bytes, "mime": str, "provider_id": str, "prompt_tokens": int,
    "completion_tokens": int, "provider_seconds": int}` — the shape every provider module returns to `render.py`.
    """
    response = submit(built, ref_bytes, api_key=api_key, base_url=base_url,
                      timeout=max(30.0, deadline - time.monotonic()))
    outcome = read_outcome(response)
    data = outcome["inline"]
    if data is None:
        wait(outcome["file_name"], api_key=api_key, base_url=base_url,
             interval=poll_interval, deadline=deadline)
        data = download(outcome["file_name"], api_key=api_key, base_url=base_url,
                        attempts=download_attempts)
    prompt_tokens, completion_tokens = usage_tokens(outcome["usage"])
    return {"data": data, "mime": outcome["mime"] or "video/mp4", "provider_id": outcome["interaction_id"],
            "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "provider_seconds": 0}
