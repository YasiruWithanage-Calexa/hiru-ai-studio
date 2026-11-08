"""Small copies of stored pictures (plan/2026-11-08c 1c, D4): 640 px wide WebP, quality 75, about 30-60 KB.

A tile on the storyboard is 200 px wide, but the stored frame is a 1536x1024 PNG of 2-3 MB. Storage cannot resize on
request on this plan, so every picture is stored TWICE: the full one, and `<path>.thumb.webp` beside it. Views carry
`thumb_url` for tiles and `url` for the large view.

Making a thumbnail is best effort: a picture that cannot be shrunk is still stored, and its tile falls back to the
full file. It never fails the work that painted the picture.
"""
from __future__ import annotations

import io
import logging

_log = logging.getLogger("hiru_ai.core.thumbs")

WIDTH = 640
QUALITY = 75
SUFFIX = ".thumb.webp"
MIME = "image/webp"
# Only these buckets hold pictures people look at in tiles; a path here never names a second file (no x-upsert).
BUCKETS = frozenset({"frames", "references"})


def thumb_path(path: str) -> str:
    return f"{path}{SUFFIX}"


def is_thumb(path: str) -> bool:
    return path.endswith(SUFFIX)


def wants_thumb(bucket: str, path: str, mime: str) -> bool:
    return bucket in BUCKETS and mime.startswith("image/") and not is_thumb(path)


def make(data: bytes, width: int = WIDTH, quality: int = QUALITY) -> bytes | None:
    """WebP bytes no wider than `width`, or None when `data` is not a picture Pillow can read."""
    try:
        from PIL import Image  # imported here: a function without Pillow still runs, just without thumbnails

        with Image.open(io.BytesIO(data)) as src:
            src.load()
            image = src.convert("RGBA" if "A" in src.getbands() else "RGB")
        if image.width > width:
            image = image.resize((width, max(1, round(image.height * width / image.width))), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, "WEBP", quality=quality, method=4)
        return out.getvalue()
    except Exception:
        _log.warning("a thumbnail could not be made", exc_info=True)
        return None
