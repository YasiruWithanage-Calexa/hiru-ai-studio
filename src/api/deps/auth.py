"""Who is calling: verify the Supabase access token, then load the caller's profile.

Tokens are verified locally. Projects on asymmetric signing keys (ES256/RS256) are checked
against the project's published JWKS, cached and refreshed once on an unknown `kid` (key
rotation). A legacy HS256 project is checked against `SUPABASE__JWT_SECRET`. There is no
network fallback: a token we cannot verify is rejected.

A refresh that fails (a network blip in the middle of a request) is retried with a short backoff
and, when it still fails, the last good keys keep serving: signing keys change rarely, so an old
copy verifies almost every token. Only a token signed by a key we have never seen needs the
network, and that one answers 503 (try again), not 401 (sign in again).

The profile is read from the database (not trusted from the token), so deactivating a person or
changing their role does not wait for their token to expire. The Supabase profiles repo caches
it for a few seconds (`PROFILE_TTL_S` in `repositories/supabase.py`), cleared when this process
writes it: a change made here applies on the next call, one made elsewhere within that TTL.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.config import Settings, get_settings
from api.deps.db import get_repos
from api.repositories import Repos
from contracts.roles import AppRole

_bearer = HTTPBearer(auto_error=False)

_logger = logging.getLogger(__name__)

_JWKS_TTL = 600.0
_JWKS_BACKOFF = (0.2, 0.6)  # waits between the attempts of one refresh, in seconds
_JWKS_RETRY_AFTER = 30.0  # after a failed refresh the old keys serve this long before the next try
_jwks: dict[str, Any] = {"keys": [], "fetched_at": 0.0}
_jwks_locks: dict[asyncio.AbstractEventLoop, asyncio.Lock] = {}


def _jwks_lock() -> asyncio.Lock:
    """One lock per event loop (tests and `--reload` run more than one loop per process)."""
    loop = asyncio.get_running_loop()
    lock = _jwks_locks.get(loop)
    if lock is None:
        _jwks_locks.clear()
        lock = _jwks_locks[loop] = asyncio.Lock()
    return lock

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Sign in again.",
    headers={"WWW-Authenticate": "Bearer"},
)


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    email: str
    display_name: str
    app_role: AppRole
    active: bool

    @property
    def is_admin(self) -> bool:
        return self.app_role is AppRole.ADMIN


def _fresh() -> bool:
    return bool(_jwks["keys"]) and time.monotonic() - _jwks["fetched_at"] < _JWKS_TTL


async def _download_jwks(settings: Settings) -> list[dict[str, Any]]:
    """The published keys, trying again after a short wait when the call fails."""
    url = f"{settings.supabase.url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    waits = (0.0, *_JWKS_BACKOFF)
    for attempt, wait in enumerate(waits, start=1):
        if wait:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
            return list(resp.json().get("keys", []))
        except httpx.HTTPError:
            if attempt == len(waits):
                raise
    raise AssertionError("unreachable")  # pragma: no cover


async def _fetch_jwks(settings: Settings, *, force: bool = False, stale_ok: bool = True) -> list[dict[str, Any]]:
    """The signing keys. `force` skips the cache (a key id we do not know); `stale_ok` lets the
    last good copy answer when the refresh fails, which the caller of a forced refresh cannot
    accept (the old copy is the one that lacked the key)."""
    if not force and _fresh():
        return _jwks["keys"]
    # One refresh at a time: requests that arrive together wait for it instead of each fetching.
    started = time.monotonic()
    async with _jwks_lock():
        if _jwks["fetched_at"] >= started or (not force and _fresh()):
            return _jwks["keys"]  # someone refreshed while we waited
        try:
            keys = await _download_jwks(settings)
        except httpx.HTTPError:
            if not (stale_ok and _jwks["keys"]):
                raise
            _logger.warning("could not refresh the signing keys; using the last good copy", exc_info=True)
            # Count the old copy as fresh for a while, so each request does not wait out the retries.
            _jwks["fetched_at"] = time.monotonic() - _JWKS_TTL + _JWKS_RETRY_AFTER
            return _jwks["keys"]
        _jwks["keys"] = keys
        _jwks["fetched_at"] = time.monotonic()
    return _jwks["keys"]


async def warm_jwks(settings: Settings) -> None:
    """Load the signing keys at startup so the first requests do not wait on them."""
    try:
        await _fetch_jwks(settings)
    except httpx.HTTPError:
        _logger.warning("could not preload JWKS; will retry on the first request", exc_info=True)


async def verify_token(token: str, settings: Settings) -> dict[str, Any]:
    """The token's claims, or 401."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise _UNAUTHORIZED from None
    alg = header.get("alg", "")
    if alg == "HS256":
        secret = settings.supabase.jwt_secret.get_secret_value()
        if not secret:
            raise _UNAUTHORIZED
        key: Any = secret
    elif alg in ("ES256", "RS256"):
        kid = header.get("kid")
        try:
            keys = await _fetch_jwks(settings)
            jwk = next((k for k in keys if k.get("kid") == kid), None)
            if jwk is None:
                keys = await _fetch_jwks(settings, force=True, stale_ok=False)
                jwk = next((k for k in keys if k.get("kid") == kid), None)
        except httpx.HTTPError:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Sign-in is unavailable.") from None
        if jwk is None:
            raise _UNAUTHORIZED
        key = jwt.PyJWK(jwk).key
    else:
        raise _UNAUTHORIZED

    try:
        return jwt.decode(token, key, algorithms=[alg], audience="authenticated",
                          options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        raise _UNAUTHORIZED from None


async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
    repos: Annotated[Repos, Depends(get_repos)],
) -> CurrentUser:
    if creds is None or creds.scheme.lower() != "bearer":
        raise _UNAUTHORIZED
    claims = await verify_token(creds.credentials, settings)
    try:
        user_id = UUID(str(claims["sub"]))
    except ValueError:
        raise _UNAUTHORIZED from None

    profile = await repos.profiles.get(user_id)
    if profile is None or not profile["active"]:
        # No profile means the account exists in Auth but was never admitted to the workspace.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account does not have access.")
    return CurrentUser(
        id=user_id,
        email=profile["email"],
        display_name=profile["display_name"],
        app_role=AppRole(profile["app_role"]),
        active=profile["active"],
    )


User = Annotated[CurrentUser, Depends(get_current_user)]
