"""The provider boundary for pictures: OpenAI's image model behind the `ImageGen` port.

What it keeps from `frame_render/engine/image.py`: one synchronous call per picture, the picture comes back inline
(nothing to download, nothing to lose between a paid generation and the bucket), reference images are sent IN THE
ORDER the prompt numbers them, and a model that DECLINES is a result to report (`ImageRefused`, never retried), not
a failure.

    no references  → images.generate
    references     → images.edit with every reference as an input image (character sheets, the location plate),
                     so the frame keeps the same faces and place
"""
from __future__ import annotations

import base64
from typing import Any

from hiru_ai.core import llm
from hiru_ai.core.ports import ImageFailed, ImageRefused, Picture, Reference
from hiru_ai.core.settings import AISettings, get_settings
from hiru_ai.core.usage import UsageSink, row, safely

# Veo 3.1 renders 16:9 and 9:16; these are the image model's nearest sizes. The frame is handed to Flow, which fits
# it to the clip.
SIZE_FOR_ASPECT = {"16:9": "1536x1024", "9:16": "1024x1536"}
_REFUSAL_CODES = {"moderation_blocked", "content_policy_violation", "safety_violation"}
_REFUSAL_HINTS = ("safety", "moderation", "content policy", "not allowed")
REFUSAL_TEXT = ("The image model declined to make this frame. Try changing the shot's description or its "
                "reference images.")
PHASE = "frame_render.image"  # the `token_usage.phase` the frame function records today


def _refused(exc: Exception) -> bool:
    code = str(getattr(exc, "code", "") or "")
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        code = code or str((body.get("error") or body).get("code") or "")
    text = str(exc).lower()
    return code in _REFUSAL_CODES or (getattr(exc, "status_code", 0) == 400 and any(h in text for h in _REFUSAL_HINTS))


class OpenAIImages:
    """`ImageGen`: paints one picture and records its tokens as a `token_usage` row (when given a sink)."""

    def __init__(self, client: Any, *, model: str, quality: str, sink: UsageSink | None = None,
                 phase: str = PHASE, draft_quality: str = "") -> None:
        self.client, self.model, self.quality, self.sink, self.phase = client, model, quality, sink, phase
        self.draft_quality = draft_quality or quality

    def __call__(self, prompt: str, aspect: str, references: list[Reference], *, draft: bool = False) -> Picture:
        size = SIZE_FOR_ASPECT.get(aspect, "1536x1024")
        quality = self.draft_quality if draft else self.quality
        try:
            if references:
                files = [(f"reference-{n}.png", ref.data, ref.mime) for n, ref in enumerate(references, start=1)]
                resp = self.client.images.edit(model=self.model, image=files, prompt=prompt, size=size,
                                               quality=quality)
            else:
                resp = self.client.images.generate(model=self.model, prompt=prompt, size=size,
                                                   quality=quality, n=1)
        except Exception as exc:
            if _refused(exc):
                raise ImageRefused(REFUSAL_TEXT) from exc
            raise ImageFailed("the image model could not make the frame") from exc
        data = resp.data[0].b64_json if resp.data else None
        if not data:
            raise ImageFailed("the image model returned no image")
        usage = getattr(resp, "usage", None)
        picture = Picture(data=base64.b64decode(data), mime="image/png",
                          input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                          output_tokens=int(getattr(usage, "output_tokens", 0) or 0))
        safely(self.sink, row(self.phase, self.model, picture.input_tokens, 0, picture.output_tokens))
        return picture


def build(settings: AISettings | None = None, *, sink: UsageSink | None = None, client: Any = None) -> OpenAIImages:
    """The painter for a run. No key raises `ModelUnavailable` (the caller reports the frame as not painted)."""
    settings = settings or get_settings()
    model, quality = llm.image_model(settings)
    return OpenAIImages(client or llm.openai_client(settings), model=model, quality=quality, sink=sink,
                        draft_quality=llm.image_draft_quality(settings))
