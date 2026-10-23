from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from api.deps.auth import CurrentUser, User
from api.deps.db import get_repos
from api.repositories import Repos
from api.schemas import Me, MeUpdate, initials

router = APIRouter(prefix="/v1/me", tags=["me"])


def _me(user: CurrentUser, display_name: str | None = None) -> Me:
    name = display_name if display_name is not None else user.display_name
    return Me(id=user.id, email=user.email, display_name=name,
              initials=initials(name, user.email), app_role=user.app_role)


@router.get("", response_model=Me)
async def get_me(user: User) -> Me:
    return _me(user)


@router.patch("", response_model=Me)
async def update_me(body: MeUpdate, user: User,
                    repos: Annotated[Repos, Depends(get_repos)]) -> Me:
    row = await repos.profiles.update(user.id, {"display_name": body.display_name.strip()})
    return _me(user, row["display_name"])
