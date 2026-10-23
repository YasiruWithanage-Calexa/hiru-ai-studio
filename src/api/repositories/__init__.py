"""All database access. Routers and services call these; nothing else talks to Supabase.

The API uses the service role, so RLS does not apply here: authorisation is enforced before a
repository is called (`api/deps/authz.py`). Rows are returned as plain dicts shaped like the
tables; routers turn them into `contracts` models.

`Repos` is a bundle of protocols so tests can swap the Supabase-backed implementation for
`tests/api/fakes.py` without patching anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

Row = dict[str, Any]


class ProfilesRepo(Protocol):
    async def get(self, user_id: UUID) -> Row | None: ...
    async def get_by_email(self, email: str) -> Row | None: ...
    async def list(self) -> list[Row]: ...
    async def update(self, user_id: UUID, fields: Row) -> Row: ...
    async def count_active_admins(self) -> int: ...


class ProductionsRepo(Protocol):
    async def list_all(self) -> list[Row]: ...
    async def list_for_member(self, user_id: UUID) -> list[tuple[Row, str]]: ...
    async def get(self, production_id: UUID) -> Row | None: ...
    async def create(self, fields: Row) -> Row: ...
    async def update(self, production_id: UUID, fields: Row) -> Row: ...


class MembersRepo(Protocol):
    async def role_of(self, production_id: UUID, user_id: UUID) -> str | None: ...
    async def list(self, production_id: UUID) -> list[Row]: ...
    async def upsert(self, production_id: UUID, user_id: UUID, role: str, added_by: UUID) -> Row: ...
    async def delete(self, production_id: UUID, user_id: UUID) -> bool: ...


class InvitationsRepo(Protocol):
    async def create(self, fields: Row) -> Row: ...
    async def delete(self, invitation_id: UUID) -> None: ...
    async def list_pending(self) -> list[Row]: ...


class AuthAdmin(Protocol):
    async def invite(self, email: str, redirect_to: str, data: Row) -> None: ...


class AuditRepo(Protocol):
    async def record(
        self,
        *,
        action: str,
        entity: str,
        entity_id: str | None,
        actor_user_id: UUID | None,
        production_id: UUID | None = None,
        diff: Row | None = None,
        actor_agent: str | None = None,
    ) -> None: ...


class JobsRepo(Protocol):
    async def create(self, fields: Row) -> Row: ...
    async def get(self, job_id: UUID) -> Row | None: ...
    async def mark_failed(self, job_id: UUID, error: str) -> None: ...
    async def events(self, job_id: UUID, after_seq: int = 0) -> list[Row]: ...


@dataclass
class Repos:
    profiles: ProfilesRepo
    productions: ProductionsRepo
    members: MembersRepo
    invitations: InvitationsRepo
    auth_admin: AuthAdmin
    audit: AuditRepo
    jobs: JobsRepo
