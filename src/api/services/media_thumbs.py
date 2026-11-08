"""Thumbnails for the API's own uploads (a person's frame or reference picture): see `hiru_ai.core.thumbs`."""
from __future__ import annotations

import asyncio
import logging

from api.repositories import Repos
from hiru_ai.core.thumbs import MIME, make, thumb_path

_logger = logging.getLogger(__name__)
__all__ = ["poster_path", "store_with_thumb", "thumb_path"]


def poster_path(take_path: str) -> str:
    """Where a take's still lives: `<shot>/<take>.mp4` -> `<shot>/<take>.poster.webp`, in the same bucket."""
    stem, dot, _ = take_path.rpartition(".")
    return f"{stem if dot else take_path}.poster.webp"


async def store_with_thumb(repos: Repos, bucket: str, path: str, data: bytes, mime: str) -> None:
    """Upload the picture and, beside it, its small WebP. A thumbnail that cannot be made or stored is skipped."""
    await repos.storage.upload(bucket, path, data, mime)
    small = await asyncio.to_thread(make, data)
    if small is None:
        return
    try:
        await repos.storage.upload(bucket, thumb_path(path), small, MIME)
    except Exception:
        _logger.warning("thumbnail of %s/%s not stored", bucket, path, exc_info=True)
