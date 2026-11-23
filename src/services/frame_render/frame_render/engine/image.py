"""The provider boundary: OpenAI's image model.

Replaces PromptMotion `video_render/engine/image.py` (Gemini "Nano Banana", 1d748dc). What is
kept is the contract: one synchronous call per picture, the picture comes back inline (nothing
to download, nothing to lose between a paid generation and the bucket), reference images are
sent IN THE ORDER the prompt numbers them, and a model that DECLINES is a result to report
(`RefusedError`, never retried), not a failure.

    no references  → images.generate
    references     → images.edit with every reference as an input image (character sheets,
                     the location plate), so the frame keeps the same faces and place
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from contracts.safe_depiction import REFUSAL_HINT

# Veo 3.1 renders 16:9 and 9:16; these are the image model's nearest sizes. The frame is
# handed to Flow, which fits it to the clip.
SIZE_FOR_ASPECT = {"16:9": "1536x1024", "9:16": "1024x1536"}
_REFUSAL_CODES = {"moderation_blocked", "content_policy_violation", "safety_violation"}
_REFUSAL_HINTS = ("safety", "moderation", "content policy", "not allowed")


class RefusedError(Exception):
    """The model declined to make the picture. Terminal and reportable."""


class ProviderError(Exception):
    """The provider failed in a way a retry inside this call could not fix."""


@dataclass(frozen=True)
class Reference:
    label: str  # what the prompt calls it ("Kamala's character sheet")
    data: bytes
    mime: str = "image/png"


@dataclass(frozen=True)
class Picture:
    data: bytes
    mime: str
    input_tokens: int
    output_tokens: int
    # Of `input_tokens`, the pictures sent in and the cached ones (plan/2026-11-23). None = the provider did not say.
    image_input_tokens: int | None = None
    cached_input_tokens: int = 0


def _get(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def input_detail(usage: Any) -> tuple[int | None, int]:
    """(picture input tokens, cached input tokens) from `usage.input_tokens_details` (plan/2026-11-23: OpenAI bills
    pictures sent in at a higher rate than text). None when the provider did not say."""
    details = _get(usage, "input_tokens_details") if usage is not None else None
    if details is None:
        return None, 0
    pictures = _get(details, "image_tokens")
    return (int(pictures) if pictures is not None else None), int(_get(details, "cached_tokens") or 0)


def _refused(exc: Exception) -> bool:
    code = str(getattr(exc, "code", "") or "")
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        code = code or str((body.get("error") or body).get("code") or "")
    text = str(exc).lower()
    return code in _REFUSAL_CODES or (getattr(exc, "status_code", 0) == 400 and any(h in text for h in _REFUSAL_HINTS))


def refusal_text(exc: Exception | None = None) -> str:
    """What a person is told. Their prompt or references, their decision to change."""
    return ("The image model declined to make this frame. Try changing the shot's description or its "
            f"reference images. {REFUSAL_HINT}")  # the hint: plan/2026-11-10b; the graph's adapter says the same


def generate(client: Any, *, model: str, quality: str, prompt: str, aspect_ratio: str,
             references: list[Reference]) -> Picture:
    size = SIZE_FOR_ASPECT.get(aspect_ratio, "1536x1024")
    try:
        if references:
            files = [(f"reference-{n}.png", ref.data, ref.mime) for n, ref in enumerate(references, start=1)]
            resp = client.images.edit(model=model, image=files, prompt=prompt, size=size, quality=quality)
        else:
            resp = client.images.generate(model=model, prompt=prompt, size=size, quality=quality, n=1)
    except Exception as exc:
        if _refused(exc):
            raise RefusedError(refusal_text(exc)) from exc
        raise ProviderError("the image model could not make the frame") from exc
    data = resp.data[0].b64_json if resp.data else None
    if not data:
        raise ProviderError("the image model returned no image")
    usage = getattr(resp, "usage", None)
    pictures, cached = input_detail(usage)
    return Picture(data=base64.b64decode(data), mime="image/png",
                   input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                   output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
                   image_input_tokens=pictures, cached_input_tokens=cached)
