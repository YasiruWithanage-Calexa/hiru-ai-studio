"""Request and response bodies that belong to the API only (not shared with functions).

Domain shapes live in `contracts`; these wrap them for HTTP.
"""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from contracts.roles import AppRole, Permission, ProductionRole


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


def initials(name: str, email: str = "") -> str:
    """"Yasiru Withanage" → "YW"; falls back to the e-mail's first letter."""
    parts = [p for p in name.split() if p[:1].isalpha()]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    if parts:
        return parts[0][:2].upper()
    return (email[:1] or "?").upper()


class Me(BaseModel):
    id: UUID
    email: str
    display_name: str
    initials: str
    app_role: AppRole


class MeUpdate(_Body):
    display_name: str = Field(min_length=1, max_length=120)


class Member(BaseModel):
    id: UUID
    email: str
    display_name: str
    initials: str
    app_role: AppRole
    active: bool


class MemberUpdate(_Body):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    app_role: AppRole | None = None
    active: bool | None = None


class InvitationCreate(_Body):
    email: EmailStr
    app_role: AppRole = AppRole.MEMBER
    production_id: UUID | None = None
    production_role: ProductionRole | None = None

    @model_validator(mode="after")
    def _pair(self) -> InvitationCreate:
        if (self.production_id is None) != (self.production_role is None):
            raise ValueError("production_id and production_role go together")
        return self


class InvitationResult(BaseModel):
    email: str
    # "invited": an invite e-mail was sent. "added": the person already had an account,
    # so the role was applied directly and no e-mail was needed.
    outcome: str


class ProductionMemberSet(_Body):
    role: ProductionRole


class MyAccess(BaseModel):
    role: ProductionRole | None
    permissions: list[Permission]
