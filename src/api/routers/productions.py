"""Productions and the people on them.

Creating a production, editing its settings or orientation, and managing its members are
admin-only (Permission.MANAGE_PRODUCTION). Everyone on a production can read it.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from api.deps.auth import User
from api.deps.authz import Admin, ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos, Row
from api.schemas import MyAccess, ProductionMemberSet
from contracts.production import (
    Production,
    ProductionCreate,
    ProductionMember,
    ProductionSettings,
    ProductionUpdate,
)
from contracts.roles import Permission, ProductionRole

router = APIRouter(prefix="/v1/productions", tags=["productions"])
ReposDep = Annotated[Repos, Depends(get_repos)]
CanView = Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))]
CanManage = Annotated[ProductionAccess, Depends(require_permission(Permission.MANAGE_PRODUCTION))]


def _production(row: Row, my_role: str | None) -> Production:
    return Production(
        id=row["id"], title=row["title"], kind=row["kind"], orientation=row["orientation"],
        status=row["status"], summary=row["summary"],
        settings=ProductionSettings.model_validate(row.get("settings") or {}),
        created_by=row.get("created_by"), created_at=row["created_at"],
        updated_at=row["updated_at"], my_role=ProductionRole(my_role) if my_role else None,
    )


@router.get("", response_model=list[Production])
async def list_productions(user: User, repos: ReposDep) -> list[Production]:
    """Every production for an admin; the ones they are on for everyone else. Newest first."""
    mine = await repos.productions.list_for_member(user.id)
    if not user.is_admin:
        return [_production(row, role) for row, role in mine]
    roles = {row["id"]: role for row, role in mine}
    return [_production(row, roles.get(row["id"])) for row in await repos.productions.list_all()]


@router.post("", response_model=Production, status_code=status.HTTP_201_CREATED)
async def create_production(body: ProductionCreate, admin: Admin, repos: ReposDep) -> Production:
    row = await repos.productions.create({**body.model_dump(mode="json"),
                                          "created_by": str(admin.id)})
    await repos.audit.record(action="production.create", entity="production",
                             entity_id=str(row["id"]), actor_user_id=admin.id,
                             production_id=row["id"], diff=body.model_dump(mode="json"))
    return _production(row, None)


@router.get("/{production_id}", response_model=Production)
async def get_production(production_id: UUID, access: CanView, repos: ReposDep) -> Production:
    return _production(access.production, access.role)


@router.patch("/{production_id}", response_model=Production)
async def update_production(production_id: UUID, body: ProductionUpdate, access: CanManage,
                            repos: ReposDep) -> Production:
    fields = body.model_dump(mode="json", exclude_unset=True)
    before = access.production
    row = await repos.productions.update(production_id, fields) if fields else before
    if fields:
        await repos.audit.record(action="production.update", entity="production",
                                 entity_id=str(production_id), actor_user_id=access.user.id,
                                 production_id=production_id,
                                 diff={k: [before.get(k), v] for k, v in fields.items()})
    return _production(row, access.role)


@router.get("/{production_id}/access", response_model=MyAccess)
async def my_access(access: CanView) -> MyAccess:
    """The caller's role and permissions here, so the UI can hide what they cannot do."""
    return MyAccess(role=access.role, permissions=sorted(access.permissions))


@router.get("/{production_id}/members", response_model=list[ProductionMember])
async def list_production_members(production_id: UUID, _: CanView,
                                  repos: ReposDep) -> list[ProductionMember]:
    rows = await repos.members.list(production_id)
    return [ProductionMember(user_id=r["user_id"], display_name=r["display_name"],
                             email=r["email"], role=r["role"]) for r in rows]


@router.put("/{production_id}/members/{user_id}", response_model=ProductionMember)
async def set_production_member(production_id: UUID, user_id: UUID, body: ProductionMemberSet,
                                access: CanManage, repos: ReposDep) -> ProductionMember:
    profile = await repos.profiles.get(user_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found.")
    before = await repos.members.role_of(production_id, user_id)
    await repos.members.upsert(production_id, user_id, body.role.value, access.user.id)
    await repos.audit.record(action="production.member_set", entity="production_member",
                             entity_id=str(user_id), actor_user_id=access.user.id,
                             production_id=production_id, diff={"role": [before, body.role.value]})
    return ProductionMember(user_id=user_id, display_name=profile["display_name"],
                            email=profile["email"], role=body.role)


@router.delete("/{production_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_production_member(production_id: UUID, user_id: UUID, access: CanManage,
                                   repos: ReposDep) -> Response:
    if not await repos.members.delete(production_id, user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not a member of this production.")
    await repos.audit.record(action="production.member_remove", entity="production_member",
                             entity_id=str(user_id), actor_user_id=access.user.id,
                             production_id=production_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
