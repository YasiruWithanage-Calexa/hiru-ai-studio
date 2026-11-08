"""Small WebP copies of stored pictures (plan/2026-11-08c 1c). The same as `hiru_ai.core.thumbs`: a service never
imports the shared library (it is bundled on its own), so this is a deliberate copy; keep the two in step."""
from __future__ import annotations

import io
import logging

_log = logging.getLogger(__name__)

WIDTH = 640
QUALITY = 75
SUFFIX = ".thumb.webp"
MIME = "image/webp"
BUCKETS = frozenset({"frames", "references"})


def thumb_path(path: str) -> str:
    return f"{path}{SUFFIX}"


def wants_thumb(bucket: str, path: str, mime: str) -> bool:
    return bucket in BUCKETS and mime.startswith("image/") and not path.endswith(SUFFIX)


def make(data: bytes, width: int = WIDTH, quality: int = QUALITY) -> bytes | None:
    try:
        from PIL import Image

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
