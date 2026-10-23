"""Who is calling: verify the Supabase access token, then load the caller's profile.

Tokens are verified locally. Projects on asymmetric signing keys (ES256/RS256) are checked
against the project's published JWKS, cached and refreshed once on an unknown `kid` (key
rotation). A legacy HS256 project is checked against `SUPABASE__JWT_SECRET`. There is no
network fallback: a token we cannot verify is rejected.

The profile is read on EVERY request (not cached in the token), so deactivating a person or
changing their role takes effect on their next call, not when their token expires.
"""
from __future__ import annotations

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

_JWKS_TTL = 600.0
_jwks: dict[str, Any] = {"keys": [], "fetched_at": 0.0}

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


async def _fetch_jwks(settings: Settings, *, force: bool = False) -> list[dict[str, Any]]:
    now = time.monotonic()
    if not force and _jwks["keys"] and now - _jwks["fetched_at"] < _JWKS_TTL:
        return _jwks["keys"]
    url = f"{settings.supabase.url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    _jwks["keys"] = resp.json().get("keys", [])
    _jwks["fetched_at"] = now
    return _jwks["keys"]


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
                keys = await _fetch_jwks(settings, force=True)
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
