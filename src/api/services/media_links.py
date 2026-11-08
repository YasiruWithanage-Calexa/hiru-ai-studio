"""Files reach the browser through THIS API, never as a link to the storage provider.

Ported from PromptMotion `api/services/media_links.py` (commit 1d748dc), which records the
full reasoning. In short, a Supabase signed URL is a bearer credential that names the project,
bucket and path, cannot be revoked, and bypasses our authorisation for its lifetime. So the API
mints its own ticket and streams the bytes itself (`routers/files.py`).

* The ticket is ENCRYPTED (AES-256-GCM), not merely signed: a readable ticket would still
  publish the bucket and path to anyone with base64.
* The key is DERIVED from the service-role key, so it can never be missing from a deploy, and
  rotating that key revokes every outstanding ticket.
* Forged, expired and malformed tickets are one answer (None → 404) on purpose.
* The same file in the same window is the same URL (plan/2026-11-08c 1a), so the browser's cache works.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from api.config import get_settings

DEFAULT_SECONDS = 3600  # covers a viewing session: seeking a video re-requests minutes later
_INFO = b"hiru/file-ticket/v1"
_AAD = b"hiru.files.v1"


def _key() -> bytes:
    secret = get_settings().supabase.service_role_key.get_secret_value()
    if not secret:
        raise RuntimeError("SUPABASE__SERVICE_ROLE_KEY is not set")
    return hmac.new(secret.encode(), _INFO, hashlib.sha256).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# A ticket that would expire sooner than this is not handed out: the browser could not use it for a page view.
MIN_REMAINING = 600


def _expiry(now: float, seconds: int) -> int:
    """The END of the current `seconds`-long window, or of the next one when under ten minutes are left in this one.
    Every ticket minted in the same window for the same file therefore has the same expiry and so the same URL
    (plan/2026-11-08c 1a). A zero or negative `seconds` is "now + seconds" (an already-expired ticket, for tests)."""
    if seconds <= 0:
        return int(now) + int(seconds)
    end = (int(now) // seconds + 1) * seconds
    return end + seconds if end - now < min(MIN_REMAINING, seconds // 2) else end


def ticket(bucket: str, path: str, seconds: int = DEFAULT_SECONDS) -> str:
    """An opaque, expiring, tamper-proof right to read ONE object.

    The same file in the same window gives a byte-identical ticket, so the browser (which caches by URL) reuses one
    download for the whole window instead of fetching the same picture under a new link every time a page reads its
    data. The nonce is derived from the plaintext (an SIV-style construction): AES-GCM is only unsafe when ONE nonce
    meets TWO different plaintexts, and here the nonce changes whenever the bucket, path or expiry does."""
    expires = _expiry(time.time(), int(seconds))
    payload = json.dumps({"b": bucket, "p": path, "e": expires}, separators=(",", ":"), sort_keys=True).encode()
    nonce = hmac.new(_key(), b"nonce|" + payload, hashlib.sha256).digest()[:12]
    return _b64(nonce + AESGCM(_key()).encrypt(nonce, payload, _AAD))


def _claims(token: str) -> dict[str, object] | None:
    try:
        raw = _unb64(token)
        claims = json.loads(AESGCM(_key()).decrypt(raw[:12], raw[12:], _AAD))
        if float(claims.get("e") or 0) < time.time():
            return None
        return dict(claims)
    except Exception:
        return None


def open_ticket(token: str) -> dict[str, str] | None:
    """`{bucket, path}` for a live ticket this API minted; None for anything else."""
    claims = _claims(token)
    if claims is None:
        return None
    bucket, path = str(claims.get("b") or ""), str(claims.get("p") or "")
    return {"bucket": bucket, "path": path} if bucket and path else None


def seconds_left(token: str) -> int:
    """Whole seconds the ticket is still good for (0 for a bad or expired one): the `max-age` of its file."""
    claims = _claims(token)
    return 0 if claims is None else max(0, int(float(str(claims.get("e") or 0)) - time.time()))


def key(bucket: str, path: str) -> str:
    """A short, stable name for ONE stored file that is safe to send to the browser (never the path itself). The same
    file has the same key for ever, though its URL changes each window, so the browser can keep one copy per key."""
    return hmac.new(_key(), f"key|{bucket}|{path}".encode(), hashlib.sha256).hexdigest()[:20]


def thumb_url(bucket: str, path: str, seconds: int = DEFAULT_SECONDS) -> str:
    """The link to a picture's small WebP copy (stored beside it, see `hiru_ai.core.thumbs`). The copy may not exist
    (a picture made before thumbnails): the browser falls back to the full file when this one answers 404."""
    return url(bucket, f"{path}.thumb.webp", seconds) if path else ""


def url(bucket: str, path: str, seconds: int = DEFAULT_SECONDS, download: str = "") -> str:
    """The absolute link to put in a response ("" for an empty path)."""
    if not path:
        return ""
    base = get_settings().api.public_url.rstrip("/")
    link = f"{base}/files/{ticket(bucket, path, seconds)}"
    return f"{link}?dl={download}" if download else link
