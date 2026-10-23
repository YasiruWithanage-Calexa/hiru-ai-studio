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
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
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


def ticket(bucket: str, path: str, seconds: int = DEFAULT_SECONDS) -> str:
    """An opaque, expiring, tamper-proof right to read ONE object."""
    payload = json.dumps({"b": bucket, "p": path, "e": int(time.time()) + int(seconds)},
                         separators=(",", ":"), sort_keys=True).encode()
    nonce = os.urandom(12)
    return _b64(nonce + AESGCM(_key()).encrypt(nonce, payload, _AAD))


def open_ticket(token: str) -> dict[str, str] | None:
    """`{bucket, path}` for a live ticket this API minted; None for anything else."""
    try:
        raw = _unb64(token)
        claims = json.loads(AESGCM(_key()).decrypt(raw[:12], raw[12:], _AAD))
        if float(claims.get("e") or 0) < time.time():
            return None
        bucket, path = str(claims.get("b") or ""), str(claims.get("p") or "")
        return {"bucket": bucket, "path": path} if bucket and path else None
    except Exception:
        return None


def url(bucket: str, path: str, seconds: int = DEFAULT_SECONDS, download: str = "") -> str:
    """The absolute link to put in a response ("" for an empty path)."""
    if not path:
        return ""
    base = get_settings().api.public_url.rstrip("/")
    link = f"{base}/files/{ticket(bucket, path, seconds)}"
    return f"{link}?dl={download}" if download else link
