"""GET /files/{ticket}: the ONE way stored files leave this product.

Ported from PromptMotion `api/routers/files.py` (commit 1d748dc). What is load-bearing:

* Range requests are forwarded and 206 is answered, or `<video>` cannot seek and Safari will
  not play at all.
* Bytes are streamed, never buffered.
* The ticket is the only authority (media elements cannot send an Authorization header), which
  is why it is narrow: one object, one hour.
* A bad ticket is 404, and the provider's error body (which names bucket and path) is dropped.
"""
from __future__ import annotations

import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from api.config import Settings, get_settings
from api.services import media_links

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
) -> StreamingResponse:
    claims = media_links.open_ticket(ticket)
    if claims is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")

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

    out = {k: v for k, v in resp.headers.items() if k.lower() in _PASS_THROUGH}
    out["Accept-Ranges"] = "bytes"
    out["Cache-Control"] = "private, max-age=3600, no-transform"
    out["Content-Disposition"] = f'attachment; filename="{_safe_name(dl)}"' if dl else "inline"
    out["X-Content-Type-Options"] = "nosniff"

    async def body():  # type: ignore[no-untyped-def]
        try:
            async for chunk in resp.aiter_bytes(_CHUNK):
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(body(), status_code=resp.status_code, headers=out)


def _safe_name(name: str) -> str:
    keep = [c for c in (name or "")[:80] if c.isalnum() or c in "-_. "]
    return "".join(keep).strip() or "download"
