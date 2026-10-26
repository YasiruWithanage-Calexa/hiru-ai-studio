"""The API's side of `infra/assemble` (ffmpeg): probe a take, pull its last frame.

Both are best effort: a take that cannot be probed is still kept (its duration is unknown), and
a last frame that cannot be made is reported so a person can upload that frame by hand. Locally
the service is a uvicorn port; on Cloud Run the API also sends a Google ID token for it.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from api.config import get_settings

_logger = logging.getLogger(__name__)


@dataclass
class Probe:
    duration_s: float
    width: int
    height: int
    has_audio: bool


class Assembler(Protocol):
    async def probe(self, bucket: str, path: str) -> Probe | None: ...
    async def last_frame(self, bucket: str, path: str, out_bucket: str, out_path: str) -> str: ...


def _id_token(audience: str) -> str:
    from google.auth.transport.requests import Request  # lazily: not needed locally
    from google.oauth2 import id_token

    return str(id_token.fetch_id_token(Request(), audience))


class HttpAssembler:
    async def _post(self, route: str, body: dict[str, Any]) -> dict[str, Any] | None:
        settings = get_settings()
        base = settings.assemble.url.rstrip("/")
        if not base:
            return None
        headers = {"X-Assemble-Secret": settings.assemble.secret.get_secret_value()}
        try:
            if not settings.local_functions:
                headers["Authorization"] = f"Bearer {await asyncio.to_thread(_id_token, base)}"
            async with httpx.AsyncClient(timeout=180.0) as client:
                r = await client.post(f"{base}{route}", json=body, headers=headers)
                r.raise_for_status()
                return dict(r.json())
        except Exception:
            _logger.warning("assemble %s failed", route, exc_info=True)
            return None

    async def probe(self, bucket: str, path: str) -> Probe | None:
        data = await self._post("/probe", {"bucket": bucket, "path": path})
        if not data or data.get("error"):
            return None
        return Probe(duration_s=float(data.get("duration_s") or 0), width=int(data.get("width") or 0),
                     height=int(data.get("height") or 0), has_audio=bool(data.get("has_audio")))

    async def last_frame(self, bucket: str, path: str, out_bucket: str, out_path: str) -> str:
        """The stored frame's path, or "" when it could not be made."""
        data = await self._post("/last-frame", {"bucket": bucket, "path": path, "out_bucket": out_bucket,
                                                "out_path": out_path})
        return str(data.get("path") or "") if data and not data.get("error") else ""


def get_assembler() -> Assembler:
    """A dependency, so tests can stand in for ffmpeg."""
    return HttpAssembler()
