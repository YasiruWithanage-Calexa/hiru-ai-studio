"""The take's length and still, read ONCE when the take is stored (plan/2026-11-21 D8).

`infra/assemble`'s `/inspect` probes the take and stores its poster in one call, reading only the bytes ffmpeg needs
(Range over a short-lived signed URL, D7). Before this the API probed a generated take on every VIEW while its length
was empty, so a take whose probe failed cost a video download on every page load.

Best effort: no `ASSEMBLE__URL` (localhost without the service), a refusal or a timeout give None and the take simply
has no length or still. On Cloud Run the service wants a Google ID token: it comes from the metadata server, so this
function needs no google-auth package.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from video_render.runtime.config import Config

_logger = logging.getLogger(__name__)
_METADATA = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity"


def poster_path(take_path: str) -> str:
    """Where a take's still lives: `<shot>/<take>.mp4` -> `<shot>/<take>.poster.webp` (api/services/media_thumbs.py)."""
    stem, dot, _ = take_path.rpartition(".")
    return f"{stem if dot else take_path}.poster.webp"


def _id_token(audience: str) -> str:
    r = httpx.get(_METADATA, params={"audience": audience}, headers={"Metadata-Flavor": "Google"}, timeout=5.0)
    r.raise_for_status()
    return r.text.strip()


def inspect(cfg: Config, bucket: str, path: str, *, client: httpx.Client | None = None) -> dict[str, Any] | None:
    """-> {"duration_s", "poster_path"} (either may be absent), or None when nothing could be read."""
    base = cfg.assemble_url.rstrip("/")
    if not base:
        return None
    headers = {"X-Assemble-Secret": cfg.assemble_secret}
    try:
        if base.startswith("https://"):  # Cloud Run: the service is not open; a local uvicorn port needs no token
            headers["Authorization"] = f"Bearer {_id_token(base)}"
        body = {"bucket": bucket, "path": path, "out_path": poster_path(path)}
        if client is None:
            with httpx.Client(timeout=120.0) as own:
                r = own.post(f"{base}/inspect", json=body, headers=headers)
        else:
            r = client.post(f"{base}/inspect", json=body, headers=headers)
        r.raise_for_status()
        data = dict(r.json())
    except Exception:
        _logger.warning("assemble /inspect failed for %s/%s", bucket, path, exc_info=True)
        return None
    found: dict[str, Any] = {}
    if float(data.get("duration_s") or 0) > 0:
        found["duration_s"] = float(data["duration_s"])
    if data.get("poster_path"):
        found["poster_path"] = str(data["poster_path"])
    return found or None
