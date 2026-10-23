"""Supabase-backed repositories (supabase-py async client, service role)."""
from __future__ import annotations

import logging
from typing import Any, cast
from uuid import UUID

from supabase import AsyncClient, acreate_client

from api.repositories import Repos, Row

_logger = logging.getLogger(__name__)


def _one(data: Any) -> Row:
    rows = cast(list[Row], data or [])
    if not rows:
        raise LookupError("no row returned")
    return rows[0]


class _Base:
    def __init__(self, db: AsyncClient) -> None:
        self.db = db


class SupabaseProfiles(_Base):
    async def get(self, user_id: UUID) -> Row | None:
        res = await self.db.table("profiles").select("*").eq("id", str(user_id)).limit(1).execute()
        return res.data[0] if res.data else None

    async def get_by_email(self, email: str) -> Row | None:
        res = await self.db.table("profiles").select("*").eq("email", email.lower()).limit(1).execute()
        return res.data[0] if res.data else None

    async def list(self) -> list[Row]:
        res = await self.db.table("profiles").select("*").order("display_name").execute()
        return cast(list[Row], res.data)

    async def update(self, user_id: UUID, fields: Row) -> Row:
        res = await self.db.table("profiles").update(fields).eq("id", str(user_id)).execute()
        return _one(res.data)

    async def count_active_admins(self) -> int:
        res = (
            await self.db.table("profiles")
            .select("id", count="exact")  # type: ignore[arg-type]
            .eq("app_role", "admin")
            .eq("active", True)
            .execute()
        )
        return res.count or 0


class SupabaseProductions(_Base):
    async def list_all(self) -> list[Row]:
        res = await self.db.table("productions").select("*").order("updated_at", desc=True).execute()
        return cast(list[Row], res.data)

    async def list_for_member(self, user_id: UUID) -> list[tuple[Row, str]]:
        res = (
            await self.db.table("production_members")
            .select("role, productions(*)")
            .eq("user_id", str(user_id))
            .execute()
        )
        pairs = [(r["productions"], r["role"]) for r in res.data or [] if r.get("productions")]
        return sorted(pairs, key=lambda p: p[0]["updated_at"], reverse=True)

    async def get(self, production_id: UUID) -> Row | None:
        res = await self.db.table("productions").select("*").eq("id", str(production_id)).limit(1).execute()
        return res.data[0] if res.data else None

    async def create(self, fields: Row) -> Row:
        res = await self.db.table("productions").insert(fields).execute()
        return _one(res.data)

    async def update(self, production_id: UUID, fields: Row) -> Row:
        res = await self.db.table("productions").update(fields).eq("id", str(production_id)).execute()
        return _one(res.data)


class SupabaseMembers(_Base):
    async def role_of(self, production_id: UUID, user_id: UUID) -> str | None:
        res = (
            await self.db.table("production_members")
            .select("role")
            .eq("production_id", str(production_id))
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )
        return res.data[0]["role"] if res.data else None

    async def list(self, production_id: UUID) -> list[Row]:
        res = (
            await self.db.table("production_members")
            .select("user_id, role, profiles!production_members_user_id_fkey(display_name, email, active)")
            .eq("production_id", str(production_id))
            .execute()
        )
        out = []
        for r in res.data or []:
            p = r.get("profiles") or {}
            out.append({"user_id": r["user_id"], "role": r["role"],
                        "display_name": p.get("display_name", ""), "email": p.get("email", ""),
                        "active": p.get("active", False)})
        return out

    async def upsert(self, production_id: UUID, user_id: UUID, role: str, added_by: UUID) -> Row:
        res = (
            await self.db.table("production_members")
            .upsert(
                {"production_id": str(production_id), "user_id": str(user_id),
                 "role": role, "added_by": str(added_by)},
                on_conflict="production_id,user_id",
            )
            .execute()
        )
        return _one(res.data)

    async def delete(self, production_id: UUID, user_id: UUID) -> bool:
        res = (
            await self.db.table("production_members")
            .delete()
            .eq("production_id", str(production_id))
            .eq("user_id", str(user_id))
            .execute()
        )
        return bool(res.data)


class SupabaseInvitations(_Base):
    async def create(self, fields: Row) -> Row:
        res = await self.db.table("invitations").insert(fields).execute()
        return _one(res.data)

    async def delete(self, invitation_id: UUID) -> None:
        await self.db.table("invitations").delete().eq("id", str(invitation_id)).execute()

    async def list_pending(self) -> list[Row]:
        res = (
            await self.db.table("invitations")
            .select("*")
            .is_("accepted_at", "null")
            .order("created_at", desc=True)
            .execute()
        )
        return cast(list[Row], res.data)


class SupabaseAuthAdmin(_Base):
    async def invite(self, email: str, redirect_to: str, data: Row) -> None:
        await self.db.auth.admin.invite_user_by_email(
            email, {"redirect_to": redirect_to, "data": data}
        )


class SupabaseAudit(_Base):
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
    ) -> None:
        row = {
            "action": action, "entity": entity, "entity_id": entity_id,
            "actor_user_id": str(actor_user_id) if actor_user_id else None,
            "production_id": str(production_id) if production_id else None,
            "diff": diff or {}, "actor_agent": actor_agent,
        }
        try:
            await self.db.table("audit_log").insert(row).execute()
        except Exception:
            # The audit trail must never be the reason a user's change fails after it was made.
            _logger.exception("audit write failed action=%s entity_id=%s", action, entity_id)


class SupabaseJobs(_Base):
    async def create(self, fields: Row) -> Row:
        res = await self.db.table("jobs").insert(fields).execute()
        return _one(res.data)

    async def get(self, job_id: UUID) -> Row | None:
        res = await self.db.table("jobs").select("*").eq("id", str(job_id)).limit(1).execute()
        return res.data[0] if res.data else None

    async def mark_failed(self, job_id: UUID, error: str) -> None:
        await self.db.table("jobs").update({"status": "failed", "error": error}).eq(
            "id", str(job_id)
        ).execute()

    async def events(self, job_id: UUID, after_seq: int = 0) -> list[Row]:
        res = (
            await self.db.table("job_events")
            .select("*")
            .eq("job_id", str(job_id))
            .gt("seq", after_seq)
            .order("seq")
            .execute()
        )
        return cast(list[Row], res.data)


async def build_supabase_repos(url: str, service_role_key: str) -> Repos:
    db = await acreate_client(url, service_role_key)
    return Repos(
        profiles=SupabaseProfiles(db),
        productions=SupabaseProductions(db),
        members=SupabaseMembers(db),
        invitations=SupabaseInvitations(db),
        auth_admin=SupabaseAuthAdmin(db),
        audit=SupabaseAudit(db),
        jobs=SupabaseJobs(db),
    )
