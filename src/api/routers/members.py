"""Workspace members and invitations. Admin only.

Sign-up is invite-only (public sign-up is off in Supabase Auth). Inviting someone who already
has an account applies the role directly instead of sending another e-mail.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from api.config import Settings, get_settings
from api.deps.authz import Admin
from api.deps.db import get_repos
from api.repositories import Repos, Row
from api.schemas import InvitationCreate, InvitationResult, Member, MemberUpdate, initials
from contracts.roles import AppRole

_logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["members"])
ReposDep = Annotated[Repos, Depends(get_repos)]


def _member(row: Row) -> Member:
    return Member(id=row["id"], email=row["email"], display_name=row["display_name"],
                  initials=initials(row["display_name"], row["email"]),
                  app_role=row["app_role"], active=row["active"])


@router.get("/members", response_model=list[Member])
async def list_members(_: Admin, repos: ReposDep) -> list[Member]:
    return [_member(r) for r in await repos.profiles.list()]


@router.patch("/members/{user_id}", response_model=Member)
async def update_member(user_id: UUID, body: MemberUpdate, admin: Admin,
                        repos: ReposDep) -> Member:
    current = await repos.profiles.get(user_id)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found.")
    fields = body.model_dump(exclude_none=True, mode="json")
    if not fields:
        return _member(current)

    # Never leave the workspace without an active admin: nobody could undo it from the app.
    loses_admin = current["app_role"] == AppRole.ADMIN and current["active"] and (
        fields.get("app_role") == AppRole.MEMBER or fields.get("active") is False
    )
    if loses_admin and await repos.profiles.count_active_admins() <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This is the last active admin. Make someone else admin first.")

    row = await repos.profiles.update(user_id, fields)
    await repos.audit.record(action="member.update", entity="profile", entity_id=str(user_id),
                             actor_user_id=admin.id,
                             diff={k: [current.get(k), v] for k, v in fields.items()})
    return _member(row)


@router.get("/invitations")
async def list_invitations(_: Admin, repos: ReposDep) -> list[dict[str, Any]]:
    return await repos.invitations.list_pending()


@router.post("/invitations", response_model=InvitationResult, status_code=status.HTTP_201_CREATED)
async def invite(body: InvitationCreate, admin: Admin, repos: ReposDep,
                 settings: Annotated[Settings, Depends(get_settings)]) -> InvitationResult:
    email = body.email.lower()
    if body.production_id and await repos.productions.get(body.production_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Production not found.")

    existing = await repos.profiles.get_by_email(email)
    if existing is not None:
        user_id = UUID(existing["id"])
        if body.app_role == AppRole.ADMIN and existing["app_role"] != AppRole.ADMIN:
            await repos.profiles.update(user_id, {"app_role": AppRole.ADMIN.value})
        if body.production_id and body.production_role:
            await repos.members.upsert(body.production_id, user_id, body.production_role.value, admin.id)
        await repos.audit.record(action="member.grant", entity="profile", entity_id=str(user_id),
                                 actor_user_id=admin.id, production_id=body.production_id,
                                 diff=body.model_dump(mode="json", exclude={"email"}))
        return InvitationResult(email=email, outcome="added")

    invitation = await repos.invitations.create({
        "email": email,
        "app_role": body.app_role.value,
        "production_id": str(body.production_id) if body.production_id else None,
        "production_role": body.production_role.value if body.production_role else None,
        "invited_by": str(admin.id),
    })
    try:
        await repos.auth_admin.invite(email, settings.supabase.invite_redirect_url,
                                      {"invited_by": str(admin.id)})
    except Exception:
        # No e-mail went out, so the invitation must not linger as if it had.
        await repos.invitations.delete(UUID(str(invitation["id"])))
        _logger.exception("invite e-mail failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            "The invitation e-mail could not be sent. Try again.") from None
    await repos.audit.record(action="member.invite", entity="invitation",
                             entity_id=str(invitation["id"]), actor_user_id=admin.id,
                             production_id=body.production_id,
                             diff=body.model_dump(mode="json"))
    return InvitationResult(email=email, outcome="invited")
