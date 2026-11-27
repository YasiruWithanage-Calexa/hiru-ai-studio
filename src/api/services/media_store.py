"""The API's calls to wherever stored files live (`hiru_ai.core.media`: Supabase Storage or Cloud Storage).

With `FILES__BACKEND=supabase` the repository keeps using the Supabase client for upload, download and removal, as
before; the functions here are its Cloud Storage side, plus the addresses the disk cache and `/files` read from.
"""
from __future__ import annotations

import asyncio

import httpx

from api.config import Settings
from hiru_ai.core import media

_TIMEOUT = httpx.Timeout(60.0, connect=10.0, write=120.0)


def media_for(settings: Settings) -> media.Media:
    """Raises ValueError on a backend that is not set up (the API calls this at start, so it fails there)."""
    files = settings.files
    config = media.MediaConfig(backend=files.backend, bucket=files.gcs_bucket.strip(),
                               read_fallback=files.read_fallback)
    return media.Media(settings.supabase.url, settings.supabase.service_role_key.get_secret_value(), config)


async def reads(settings: Settings, bucket: str, path: str) -> list[media.Request]:
    """Where to read one file, in order (off the event loop: a Google token may have to be fetched)."""
    return await asyncio.to_thread(media_for(settings).reads, bucket, path)


async def upload(settings: Settings, bucket: str, path: str, data: bytes, content_type: str) -> None:
    """Create the object; an existing one is an error, as with the Supabase client's default."""
    request = await asyncio.to_thread(media_for(settings).write, bucket, path, content_type, once=True)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(request.url, headers=request.headers, content=data)
    response.raise_for_status()


async def download(settings: Settings, bucket: str, path: str) -> bytes:
    requests = await reads(settings, bucket, path)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for i, request in enumerate(requests):
            response = await client.get(request.url, headers=request.headers)
            if response.status_code != 404 or i == len(requests) - 1:
                break
    response.raise_for_status()
    return response.content


async def remove(settings: Settings, bucket: str, path: str) -> None:
    """Remove the object everywhere it is read from (an already missing one is fine)."""
    requests = await asyncio.to_thread(media_for(settings).removes, bucket, path)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for request in requests:
            response = await client.delete(request.url, headers=request.headers)
            # Supabase answers a missing object with 400 and "not_found" in the body.
            missing = response.status_code == 404 or (response.status_code == 400 and "not_found" in response.text)
            if not missing:
                response.raise_for_status()
