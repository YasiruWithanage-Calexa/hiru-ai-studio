"""What the caller may do. Every route declares exactly one of these.

    require_admin                          workspace administration
    require_permission(Permission.X)       an action on the production in the path

A production the caller cannot see answers 404, not 403: whether a production exists is not
something a non-member gets to learn. A production they CAN see but may not act on answers 403,
naming nothing beyond "your role".
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status

from api.deps.auth import CurrentUser, User
from api.deps.db import get_repos
from api.repositories import Repos
from contracts.roles import Permission, ProductionRole, permissions_for

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Production not found.")


async def require_admin(user: User) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an admin can do this.")
    return user


Admin = Annotated[CurrentUser, Depends(require_admin)]


@dataclass(frozen=True)
class ProductionAccess:
    user: CurrentUser
    production_id: UUID
    role: ProductionRole | None  # None for an admin who is not a member
    permissions: frozenset[Permission]


async def resolve_access(user: CurrentUser, production_id: UUID, repos: Repos) -> ProductionAccess:
    """The caller's role and permissions on one production, or 404 if they cannot see it."""
    role_name = await repos.members.role_of(production_id, user.id)
    role = ProductionRole(role_name) if role_name else None
    if role is None and not user.is_admin:
        raise NOT_FOUND
    if await repos.productions.get(production_id) is None:
        raise NOT_FOUND
    return ProductionAccess(user, production_id, role, permissions_for(user.app_role, role))


def require_permission(
    permission: Permission,
) -> Callable[..., Awaitable[ProductionAccess]]:
    """A dependency for routes with a `{production_id}` path parameter."""

    async def dependency(
        production_id: UUID,
        user: User,
        repos: Annotated[Repos, Depends(get_repos)],
    ) -> ProductionAccess:
        access = await resolve_access(user, production_id, repos)
        if permission not in access.permissions:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role on this production does not allow this.")
        return access

    dependency.__name__ = f"require_{permission.value}"
    return dependency
