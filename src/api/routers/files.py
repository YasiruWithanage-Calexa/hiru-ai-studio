"""GET /files/{ticket}: the ONE way stored files leave this product.

Ported from PromptMotion `api/routers/files.py` (commit 1d748dc). What is load-bearing:

* Range requests are answered with 206, or `<video>` cannot seek and Safari will not play at all.
* A file is downloaded from the storage provider ONCE and kept on this machine's disk (`services/file_cache.py`);
  every later request is served from there. Only a file bigger than the cache is streamed through, never buffered.
* The ticket is the only authority (media elements cannot send an Authorization header), which
  is why it is narrow: one object, one hour.
* A bad ticket is 404, and the provider's error body (which names bucket and path) is dropped.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Annotated
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, Response, StreamingResponse

from api.config import Settings, get_settings
from api.services import file_cache, media_links

_logger = logging.getLogger(__name__)
router = APIRouter(tags=["files"])

_TIMEOUT = httpx.Timeout(30.0, read=300.0)
_CHUNK = 64 * 1024
_PASS_THROUGH = ("content-type", "content-length", "content-range", "accept-ranges",
                 "etag", "last-modified")


@router.get("/files/{ticket}")
async def serve(
    ticket: str,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    range_: Annotated[str | None, Header(alias="range")] = None,
    dl: str = "",
) -> Response:
    claims = media_links.open_ticket(ticket)
    if claims is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")

    # `immutable` is true because a media path is never overwritten (plan/2026-11-08c 1d) and the ticket for a file is
    # the same URL all window long (1a): the browser keeps its copy until the ticket would have expired anyway.
    left = max(media_links.seconds_left(ticket), 1)
    out = {"Cache-Control": f"private, max-age={left}, immutable, no-transform", "X-Content-Type-Options": "nosniff",
           "Content-Disposition": _disposition(dl)}

    cache = file_cache.get_cache(settings)
    try:
        cached = await cache.fetch(claims["bucket"], claims["path"])
    except file_cache.NotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.") from None
    except file_cache.Unreachable:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "That file could not be read.") from None
    except file_cache.TooLarge:
        return await _stream_through(claims, request, settings, range_, out)
    return FileResponse(cached.path, media_type=cached.media_type, headers=out)


async def _stream_through(claims: dict[str, str], request: Request, settings: Settings, range_: str | None,
                          out: dict[str, str]) -> StreamingResponse:
    """The old path, kept for a file bigger than the whole disk cache (or with the cache switched off): nothing is kept,
    Range is forwarded, bytes are streamed."""
    upstream = (f"{settings.supabase.url.rstrip('/')}/storage/v1/object/"
                f"{claims['bucket']}/{claims['path']}")
    headers = {"Authorization": f"Bearer {settings.supabase.service_role_key.get_secret_value()}"}
    if range_:
        headers["Range"] = range_
    for name in ("if-none-match", "if-modified-since"):
        if name in request.headers:
            headers[name] = request.headers[name]

    client = httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        resp = await client.send(client.build_request("GET", upstream, headers=headers), stream=True)
    except httpx.HTTPError:
        await client.aclose()
        _logger.warning("storage unreachable bucket=%s", claims["bucket"], exc_info=True)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "That file could not be read.") from None

    if resp.status_code >= 400:
        await resp.aclose()
        await client.aclose()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")

    headers_out = {k: v for k, v in resp.headers.items() if k.lower() in _PASS_THROUGH}
    headers_out["Accept-Ranges"] = "bytes"
    headers_out.update(out)

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in resp.aiter_bytes(_CHUNK):
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(body(), status_code=resp.status_code, headers=headers_out)


def _disposition(name: str) -> str:
    if not name:
        return "inline"
    plain = _safe_name(name)
    ascii_name = plain.encode("ascii", "ignore").decode().strip() or "download"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(plain)}"


def _safe_name(name: str) -> str:
    keep = [c for c in (name or "")[:80] if c.isalnum() or c in "-_. "]
    return "".join(keep).strip() or "download"
