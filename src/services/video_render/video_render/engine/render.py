"""One render, start to finish: the only place that decides what a render's outcome IS.

claim → generate → store → record, and each step exists because of a specific way this goes wrong:

  claim    — a Cloud Task can be re-delivered, and a re-delivered video generation is a second video someone pays for.
             The `video_renders` row is the lock: the API inserted it `queued`, and this CLAIMS it with a conditional
             update. Zero rows back means a sibling invocation won the race, which is the mechanism working.
  generate — the provider boundary (`omni.py`, `veo.py`). A refusal comes back as a result, not an exception to retry.
  store    — retrieval retries to exhaustion, because the video already cost money. The file is stored under a path
             derived from the render id, so a retry overwrites instead of leaving a second file.
  record   — the take, then the render, then the usage row. In that order: a video that exists but is recorded nowhere
             is money with no artifact attached to it.

Never raises: every outcome is a status the caller records and answers 200 for. Forked from PromptMotion
`engine/take.py` (see ../../UPSTREAM.md).
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx
from pydantic import ValidationError

from contracts.video_gen import RenderSpec, build_request, capability, request_hash, validate_render
from video_render.engine import fake, omni, veo
from video_render.engine.transport import ProviderError, RefusedError
from video_render.runtime.config import Config
from video_render.runtime.rest import Row
from video_render.runtime.store import TAKES_BUCKET

_logger = logging.getLogger(__name__)

# Engine key → the provider module that renders it. Each exposes the same `generate(...)`.
PROVIDERS = {"omni_flash": omni, "veo_3_1": veo, "veo_3_1_fast": veo}

FAILED = "The video could not be made. Try again in a moment."
UNAVAILABLE = "Video generation is not set up on this server."
CHANGED = "The request changed after it was checked. Open the shot and press Generate again."
EXPIRED = "The video took too long and could not be picked up again. Try again."
BUCKETS = ("frames", "references", "takes")


def _mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _own(path: str, production_id: str) -> bool:
    """A reference path is under this production and goes nowhere else: the service role can read every object in
    every bucket, so the shape of the path is the whole authorisation."""
    parts = path.split("/")
    return path.startswith(f"{production_id}/") and ".." not in parts and "" not in parts[1:]


def take_id_for(render_id: str) -> str:
    """The take a render makes has a fixed id, so a crash between storing and recording is repaired by the retry."""
    return str(uuid5(NAMESPACE_URL, f"hiru:take:{render_id}"))


def resumable(engine: str) -> bool:
    return bool(getattr(PROVIDERS.get(engine), "RESUMABLE", False))


def resume_claim(store: Any, row: Row, cfg: Config, *, now: float | None = None) -> tuple[str, str]:
    """What a re-delivered task does with a render it could not claim. → (decision, provider id)

      "skip"   — nothing to resume (finished, never submitted, or an engine that cannot resume)
      "later"  — submitted too recently; the first invocation may still be polling it
      "resume" — this invocation now owns the poll of that provider job
      "expire" — picked up too many times already; the caller fails the render

    The ownership step is a compare-and-swap on `provider_id` (`<id>` → `<id>#1` → `<id>#2`), so two re-deliveries
    racing cannot both resume."""
    if not resumable(str(row.get("engine"))):
        return "skip", ""
    current = str(row.get("provider_id") or "")
    if row.get("status") != "running" or not current:
        return "skip", ""
    base, _, count = current.partition("#")
    attempts = int(count) if count.isdigit() else 0
    usage = row.get("usage") or {}
    now = time.time() if now is None else now
    if now - float(usage.get("submitted_at") or 0) < cfg.resume_after_s:
        return "later", ""
    if attempts >= cfg.max_resumes:
        return "expire", base
    swapped = store.swap_provider_id(str(row["id"]), current, f"{base}#{attempts + 1}",
                                     {**usage, "submitted_at": now, "resumed": attempts + 1})
    return ("resume", base) if swapped else ("skip", "")


def _fail(store: Any, rid: str, error: str, usage: Row | None = None) -> str:
    fields: Row = {"status": "failed", "error": error}
    if usage:
        fields["usage"] = usage
    store.finish_render(rid, fields)
    return "failed"


def run_render(store: Any, cfg: Config, row: Row, *, job_id: str, actor: str) -> str:
    """→ "done" | "failed" | "refused" | "skipped"."""
    rid = str(row["id"])
    resume_id = ""
    if not store.claim_render(rid):
        fresh = store.render(rid)
        if fresh is None:
            return "skipped"
        decision, provider_id = resume_claim(store, fresh, cfg)
        if decision == "expire":
            return _fail(store, rid, EXPIRED)
        if decision != "resume":
            return "skipped"
        row, resume_id = fresh, provider_id
    started = time.monotonic()
    try:
        return _render(store, cfg, row, job_id=job_id, actor=actor, resume_id=resume_id, started=started)
    except RefusedError as exc:
        # A refusal is a RESULT. It is reported, and — because this returns normally — never retried by Cloud Tasks.
        store.finish_render(rid, {"status": "refused", "refusal": str(exc),
                                  "usage": {"engine": row.get("engine"), "latency_ms": _ms(started)}})
        return "refused"
    except ProviderError as exc:
        # Written for people already ("the video was still processing when time ran out").
        said = str(exc).rstrip()
        said = said[:1].upper() + said[1:]
        return _fail(store, rid, f"{said}{'' if said.endswith(('.', '!', '?')) else '.'}",
                     {"engine": row.get("engine"), "latency_ms": _ms(started)})
    except httpx.TransportError:
        raise  # the handler answers 500: nothing was submitted that a retry would repeat (see handler)
    except Exception:
        _logger.exception("render %s failed", rid)
        return _fail(store, rid, FAILED, {"engine": row.get("engine"), "latency_ms": _ms(started)})


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _render(store: Any, cfg: Config, row: Row, *, job_id: str, actor: str, resume_id: str, started: float) -> str:
    rid, production_id = str(row["id"]), str(row["production_id"])
    try:
        spec = RenderSpec.model_validate(row["spec"])
    except ValidationError:
        return _fail(store, rid, CHANGED)
    if not cfg.can_render:
        _logger.warning("NO GOOGLE__API_KEY: set it for this function (render %s)", rid)
        return _fail(store, rid, UNAVAILABLE)

    # The API validated this before it spent anything; re-checking is the backstop for a row that reached us some
    # other way. The hash proves the stored request is the one that was checked.
    issues = [c.label for c in validate_render(spec)]
    if request_hash(spec) != row.get("request_hash"):
        issues.append(CHANGED)
    for ref in spec.references:
        if ref.source.bucket not in BUCKETS or not _own(ref.source.path, production_id):
            issues.append("A reference picture is not one of this production's.")
    if issues:
        return _fail(store, rid, "; ".join(dict.fromkeys(issues)))

    cap = capability(spec.engine)
    built = build_request(spec)
    if spec.model == cap.model:  # the person did not choose a model: the deploy may (VIDEO__MODELS)
        built["model"] = cfg.models.get(spec.engine, built["model"])
    provider = PROVIDERS[spec.engine]

    # Each picture named once by (bucket, path): the same picture bound twice is downloaded once, sent twice.
    pictures: dict[tuple[str, str], bytes] = {}
    if not resume_id:
        for part in built["references"]:
            key = (part["bucket"], part["path"])
            if key not in pictures:
                pictures[key] = store.download(*key)
    ref_bytes = {path: (data, _mime(data)) for (_, path), data in pictures.items()}

    def submitted(provider_id: str) -> None:
        try:
            store.mark_submitted(rid, provider_id, {"engine": spec.engine, "submitted_at": time.time()})
        except Exception:
            _logger.warning("could not record the provider id of render %s", rid, exc_info=True)

    if cfg.fake_provider:
        outcome = fake.generate(built, ref_bytes)
    else:
        extra: dict[str, Any] = {"on_submitted": submitted, "resume_id": resume_id} if resumable(spec.engine) else {}
        outcome = provider.generate(built, ref_bytes, api_key=cfg.google_api_key, base_url=cfg.google_base_url,
                                    deadline=started + cfg.take_timeout_s, poll_interval=cfg.poll_interval_s,
                                    download_attempts=cfg.download_attempts, **extra)

    data: bytes = outcome["data"]
    mime = outcome["mime"] or "video/mp4"
    take_id = take_id_for(rid)
    ext = {"video/webm": "webm", "video/quicktime": "mov"}.get(mime, "mp4")
    path = f"{production_id}/{row['shot_id']}/{take_id}.{ext}"
    store.upload(TAKES_BUCKET, path, data, mime)
    try:
        store.create_take({
            "id": take_id, "production_id": production_id, "shot_id": str(row["shot_id"]),
            "prompt_id": str(spec.prompt_id) if spec.prompt_id else None, "prompt_version": spec.prompt_version,
            "storage_path": path, "mime": mime, "bytes": len(data), "duration_s": None, "origin": "generated",
            "render_id": rid, "uploaded_by": row.get("created_by")})
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 409:  # already recorded by an earlier attempt: the same take
            raise

    # The sha256 of every picture that went, recorded now that the bytes are in hand: proof of which pictures were sent.
    for ref in spec.references:
        got = pictures.get((ref.source.bucket, ref.source.path))
        if got is not None:
            ref.source.sha256 = hashlib.sha256(got).hexdigest()
    seconds = int(outcome.get("provider_seconds") or 0)
    output_tokens = int(outcome.get("completion_tokens") or 0) or seconds * cfg.tokens_per_second.get(spec.engine, 0)
    usage = {"engine": spec.engine, "model": built["model"], "resolution": spec.resolution,
             "aspect_ratio": spec.aspect_ratio, "seconds": spec.duration_s, "refs": len(built["references"]),
             "latency_ms": _ms(started), "bytes": len(data), "prompt_tokens": int(outcome.get("prompt_tokens") or 0),
             "completion_tokens": int(outcome.get("completion_tokens") or 0), "provider_seconds": seconds,
             "resumed": bool(resume_id), "mime": mime}
    store.finish_render(rid, {"status": "done", "take_id": take_id, "provider_id": outcome.get("provider_id") or None,
                              "usage": usage, "error": None, "refusal": None,
                              "spec": spec.model_dump(mode="json")})
    store.record_usage({"job_id": job_id, "production_id": production_id, "actor_user_id": actor,
                        "phase": f"video_render.{spec.engine}", "model": built["model"],
                        "input_tokens": usage["prompt_tokens"], "cached_input_tokens": 0,
                        "output_tokens": output_tokens})
    return "done"
