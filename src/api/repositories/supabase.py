"""Supabase-backed repositories (supabase-py async client, service role)."""
from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from supabase import AsyncClient, acreate_client

from api.cache import AsyncTTLCache
from api.observability import count_db_call
from api.repositories import Repos, Row

_logger = logging.getLogger(__name__)


def _rows(data: Any) -> list[Row]:
    """supabase-py types `.data` as any JSON value; every query here returns a list of rows."""
    return cast(list[Row], data or [])


def _first(data: Any) -> Row | None:
    rows = _rows(data)
    return rows[0] if rows else None


def _one(data: Any) -> Row:
    rows = _rows(data)
    if not rows:
        raise LookupError("no row returned")
    return rows[0]


class _Base:
    def __init__(self, db: AsyncClient) -> None:
        self.db = db


# Every authenticated request reads the caller's profile; a page fires several requests at once.
PROFILE_TTL_S = 30.0


class SupabaseProfiles(_Base):
    def __init__(self, db: AsyncClient) -> None:
        super().__init__(db)
        self._cache: AsyncTTLCache[Row] = AsyncTTLCache(PROFILE_TTL_S)

    async def get(self, user_id: UUID) -> Row | None:
        row = await self._cache.get(str(user_id), lambda: self._get(user_id))
        return dict(row) if row else None

    async def _get(self, user_id: UUID) -> Row | None:
        res = await self.db.table("profiles").select("*").eq("id", str(user_id)).limit(1).execute()
        return _first(res.data)

    async def get_by_email(self, email: str) -> Row | None:
        res = await self.db.table("profiles").select("*").eq("email", email.lower()).limit(1).execute()
        return _first(res.data)

    async def list(self) -> list[Row]:
        res = await self.db.table("profiles").select("*").order("display_name").execute()
        return _rows(res.data)

    async def update(self, user_id: UUID, fields: Row) -> Row:
        self._cache.invalidate(str(user_id))
        res = await self.db.table("profiles").update(fields).eq("id", str(user_id)).execute()
        self._cache.invalidate(str(user_id))
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
        return _rows(res.data)

    async def list_for_member(self, user_id: UUID) -> list[tuple[Row, str]]:
        res = (
            await self.db.table("production_members")
            .select("role, productions(*)")
            .eq("user_id", str(user_id))
            .execute()
        )
        pairs = [(r["productions"], r["role"]) for r in _rows(res.data) if r.get("productions")]
        return sorted(pairs, key=lambda p: p[0]["updated_at"], reverse=True)

    async def get(self, production_id: UUID) -> Row | None:
        res = await self.db.table("productions").select("*").eq("id", str(production_id)).limit(1).execute()
        return _first(res.data)

    async def get_with_role(self, production_id: UUID, user_id: UUID) -> tuple[Row, str | None] | None:
        # One round trip: the production with the caller's membership embedded (filtered to them).
        res = (
            await self.db.table("productions")
            .select("*, production_members(role)")
            .eq("id", str(production_id))
            .eq("production_members.user_id", str(user_id))
            .limit(1)
            .execute()
        )
        row = _first(res.data)
        if row is None:
            return None
        members = row.pop("production_members", None) or []
        return row, (members[0]["role"] if members else None)

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
        row = _first(res.data)
        return row["role"] if row else None

    async def list(self, production_id: UUID) -> list[Row]:
        res = (
            await self.db.table("production_members")
            .select("user_id, role, profiles!production_members_user_id_fkey(display_name, email, active)")
            .eq("production_id", str(production_id))
            .execute()
        )
        out = []
        for r in _rows(res.data):
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
        return _rows(res.data)


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

    async def list(self, production_id: UUID, limit: int = 100) -> list[Row]:
        res = (await self.db.table("audit_log").select("*").eq("production_id", str(production_id))
               .order("created_at", desc=True).order("id", desc=True).limit(limit).execute())
        return _rows(res.data)


class SupabaseJobs(_Base):
    async def create(self, fields: Row) -> Row:
        res = await self.db.table("jobs").insert(fields).execute()
        return _one(res.data)

    async def get(self, job_id: UUID) -> Row | None:
        res = await self.db.table("jobs").select("*").eq("id", str(job_id)).limit(1).execute()
        return _first(res.data)

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
        return _rows(res.data)


    async def latest(self, production_id: UUID, kind: str) -> Row | None:
        res = (await self.db.table("jobs").select("*").eq("production_id", str(production_id))
               .eq("kind", kind).order("created_at", desc=True).limit(1).execute())
        return _first(res.data)

    async def advance(self, job_id: UUID, from_cursor: int, request: Row | None = None) -> bool:
        fields: Row = {"cursor": from_cursor + 1, **({"request": request} if request is not None else {})}
        res = (await self.db.table("jobs").update(fields).eq("id", str(job_id))
               .eq("cursor", from_cursor).in_("status", ["running", "pending"]).execute())
        return bool(res.data)

    async def claim_resume(self, job_id: UUID) -> bool:
        res = (await self.db.table("jobs").update({"status": "running"}).eq("id", str(job_id))
               .eq("status", "waiting_input").execute())
        return bool(res.data)


class SupabaseDocuments(_Base):
    async def create(self, fields: Row) -> Row:
        res = await self.db.table("documents").insert(fields).execute()
        return _one(res.data)

    async def get(self, production_id: UUID, document_id: UUID) -> Row | None:
        res = (await self.db.table("documents").select("*").eq("id", str(document_id))
               .eq("production_id", str(production_id)).limit(1).execute())
        return _first(res.data)

    async def find_by_hash(self, production_id: UUID, sha256: str) -> Row | None:
        res = (await self.db.table("documents").select("*").eq("production_id", str(production_id))
               .eq("sha256", sha256).limit(1).execute())
        return _first(res.data)

    async def list(self, production_id: UUID) -> list[Row]:
        res = (await self.db.table("documents").select("*").eq("production_id", str(production_id))
               .order("created_at", desc=True).execute())
        return _rows(res.data)

    async def update(self, document_id: UUID, fields: Row) -> Row:
        res = await self.db.table("documents").update(fields).eq("id", str(document_id)).execute()
        return _one(res.data)

    async def delete(self, document_id: UUID) -> None:
        await self.db.table("documents").delete().eq("id", str(document_id)).execute()


class SupabaseStorage(_Base):
    async def upload(self, bucket: str, path: str, data: bytes, content_type: str) -> None:
        await self.db.storage.from_(bucket).upload(path, data, {"content-type": content_type})

    async def remove(self, bucket: str, path: str) -> None:
        await self.db.storage.from_(bucket).remove([path])

    async def download(self, bucket: str, path: str) -> bytes:
        return bytes(await self.db.storage.from_(bucket).download(path))


def _vector(values: list[float] | None) -> str | None:
    """pgvector's text form; PostgREST passes it straight to the vector parameter."""
    return None if values is None else "[" + ",".join(f"{v:.7g}" for v in values) + "]"


class SupabaseSearch(_Base):
    async def match_chunks(self, *, query_text: str, query_embedding: list[float] | None,
                           production_id: UUID | None, corpora: list[str],
                           document_ids: list[UUID] | None, match_count: int) -> list[Row]:
        res = await self.db.rpc("match_chunks", {
            "query_text": query_text,
            "query_embedding": _vector(query_embedding),
            "p_production_id": str(production_id) if production_id else None,
            "p_corpora": corpora,
            "p_document_ids": [str(d) for d in document_ids] if document_ids is not None else None,
            "match_count": match_count,
        }).execute()
        return _rows(res.data)

    async def match_techniques(self, *, query_text: str, query_embedding: list[float] | None,
                               domain: str, categories: list[str] | None, match_count: int) -> list[Row]:
        res = await self.db.rpc("match_craft_techniques", {
            "query_text": query_text, "query_embedding": _vector(query_embedding),
            "match_domain": domain, "match_categories": categories, "match_count": match_count,
        }).execute()
        return _rows(res.data)


class SupabaseUsage(_Base):
    async def record(self, row: Row) -> None:
        try:
            await self.db.table("token_usage").insert(row).execute()
        except Exception:
            _logger.exception("token usage write failed phase=%s", row.get("phase"))

    async def tokens_since(self, since: datetime) -> int:
        res = await self.db.rpc("token_usage_since", {"since": since.isoformat()}).execute()
        return int(cast(int, res.data or 0))

    async def budget(self, month: str) -> int | None:
        try:
            res = await self.db.table("usage_budget").select("budget_tokens").eq("month", month).limit(1).execute()
        except Exception:  # the table arrives with schema v4; before that the setting applies
            _logger.warning("usage_budget unavailable", exc_info=True)
            return None
        row = _first(res.data)
        return int(row["budget_tokens"]) if row else None

    async def set_budget(self, month: str, tokens: int, user_id: UUID) -> None:
        await self.db.table("usage_budget").upsert({"month": month, "budget_tokens": tokens,
                                                    "set_by": str(user_id)}, on_conflict="month").execute()


class SupabaseEpisodes(_Base):
    async def list(self, production_id: UUID) -> list[Row]:
        res = (await self.db.table("episodes").select("*").eq("production_id", str(production_id))
               .order("number").execute())
        return _rows(res.data)

    async def get(self, production_id: UUID, episode_id: UUID) -> Row | None:
        res = (await self.db.table("episodes").select("*").eq("id", str(episode_id))
               .eq("production_id", str(production_id)).limit(1).execute())
        return _first(res.data)

    async def update(self, episode_id: UUID, fields: Row) -> Row:
        res = await self.db.table("episodes").update(fields).eq("id", str(episode_id)).execute()
        return _one(res.data)


class SupabaseScenes(_Base):
    async def list(self, production_id: UUID, episode_id: UUID | None = None) -> list[Row]:
        q = self.db.table("scenes").select("*").eq("production_id", str(production_id))
        if episode_id is not None:
            q = q.eq("episode_id", str(episode_id))
        res = await q.order("number").execute()
        return _rows(res.data)

    async def get(self, production_id: UUID, scene_id: UUID) -> Row | None:
        res = (await self.db.table("scenes").select("*").eq("id", str(scene_id))
               .eq("production_id", str(production_id)).limit(1).execute())
        return _first(res.data)

    async def update(self, scene_id: UUID, fields: Row) -> Row:
        res = await self.db.table("scenes").update(fields).eq("id", str(scene_id)).execute()
        return _one(res.data)


class SupabaseShots(_Base):
    async def get(self, production_id: UUID, shot_id: UUID) -> Row | None:
        res = (await self.db.table("shots").select("*").eq("id", str(shot_id))
               .eq("production_id", str(production_id)).limit(1).execute())
        return _first(res.data)

    async def update(self, shot_id: UUID, fields: Row) -> Row:
        res = await self.db.table("shots").update(fields).eq("id", str(shot_id)).execute()
        return _one(res.data)

    async def save_plan(self, shots: list[Row], removed: list[str]) -> None:
        if removed:
            await self.db.table("shots").delete().in_("id", removed).execute()
        if shots:
            await self.db.table("shots").upsert(shots, on_conflict="id").execute()

    async def list(self, production_id: UUID, scene_id: UUID | None = None) -> list[Row]:
        q = self.db.table("shots").select("*").eq("production_id", str(production_id))
        if scene_id is not None:
            q = q.eq("scene_id", str(scene_id))
        res = await q.order("number").execute()
        return _rows(res.data)


class SupabaseLines(_Base):
    async def upsert(self, rows: list[Row]) -> None:
        if rows:
            await self.db.table("dialogue_lines").upsert(rows, on_conflict="id").execute()

    async def delete(self, line_ids: list[str]) -> None:
        if line_ids:
            await self.db.table("dialogue_lines").delete().in_("id", line_ids).execute()

    async def list_for_production(self, production_id: UUID) -> list[Row]:
        res = (await self.db.table("dialogue_lines").select("id,scene_id,shot_id,character_id")
               .eq("production_id", str(production_id)).execute())
        return _rows(res.data)

    async def list(self, scene_id: UUID) -> list[Row]:
        res = await self.db.table("dialogue_lines").select("*").eq("scene_id", str(scene_id)).order("ord").execute()
        return _rows(res.data)


_PERSONA = "id, slug, name, initials, color, specialty, traits, style_note, charter, active"


class SupabasePersonas(_Base):
    async def get_many(self, persona_ids: list[UUID]) -> list[Row]:
        if not persona_ids:
            return []
        res = await self.db.table("director_personas").select(_PERSONA).in_(
            "id", [str(p) for p in persona_ids]).execute()
        return _rows(res.data)

    async def list(self) -> list[Row]:
        res = await self.db.table("director_personas").select(_PERSONA).eq("active", True).order("name").execute()
        return _rows(res.data)


class SupabaseBoard(_Base):
    async def replace(self, production_id: UUID, seats: list[Row], added_by: UUID) -> None:
        # Two statements: a reader in between sees an empty board for a moment, never a board
        # with two leads (the partial unique index forbids it).
        await self.db.table("production_director_board").delete().eq("production_id", str(production_id)).execute()
        await self.db.table("production_director_board").insert([
            {"production_id": str(production_id), "persona_id": str(s["persona_id"]), "seat": s["seat"],
             "added_by": str(added_by)} for s in seats]).execute()

    async def list(self, production_id: UUID) -> list[Row]:
        res = (await self.db.table("production_director_board")
               .select(f"seat, persona_id, created_at, persona:director_personas({_PERSONA})")
               .eq("production_id", str(production_id)).order("created_at").execute())
        return _rows(res.data)


class SupabaseThreads(_Base):
    async def get(self, production_id: UUID, thread_id: UUID) -> Row | None:
        res = (await self.db.table("chat_threads").select("*").eq("id", str(thread_id))
               .eq("production_id", str(production_id)).limit(1).execute())
        return _first(res.data)

    async def create(self, fields: Row) -> Row:
        res = await self.db.table("chat_threads").insert(fields).execute()
        return _one(res.data)

    async def touch(self, thread_id: UUID) -> None:
        await self.db.table("chat_threads").update({"updated_at": datetime.now(UTC).isoformat()}).eq(
            "id", str(thread_id)).execute()

    async def list(self, production_id: UUID, scene_id: UUID | None = None) -> list[Row]:
        q = self.db.table("chat_threads").select("*").eq("production_id", str(production_id))
        if scene_id is not None:
            q = q.eq("scene_id", str(scene_id))
        res = await q.order("created_at").execute()
        return _rows(res.data)


class SupabaseMessages(_Base):
    async def create(self, fields: Row) -> Row:
        res = await self.db.table("chat_messages").insert(fields).execute()
        return _one(res.data)

    async def get(self, production_id: UUID, message_id: UUID) -> Row | None:
        res = (await self.db.table("chat_messages").select("*").eq("id", str(message_id))
               .eq("production_id", str(production_id)).limit(1).execute())
        return _first(res.data)

    async def update(self, message_id: UUID, fields: Row) -> Row:
        res = await self.db.table("chat_messages").update(fields).eq("id", str(message_id)).execute()
        return _one(res.data)

    async def list(self, thread_id: UUID, limit: int = 100) -> list[Row]:
        res = (await self.db.table("chat_messages").select("*").eq("thread_id", str(thread_id))
               .order("created_at", desc=True).limit(limit).execute())
        return _rows(res.data)[::-1]

    async def clear(self, thread_id: UUID) -> None:
        await self.db.table("chat_messages").delete().eq("thread_id", str(thread_id)).execute()


class SupabaseMemory(_Base):
    async def get(self, production_id: UUID, item_id: UUID) -> Row | None:
        res = (await self.db.table("memory_items").select("*").eq("id", str(item_id))
               .eq("production_id", str(production_id)).limit(1).execute())
        return _first(res.data)

    async def add(self, item: Row, embedding: list[float] | None, embedding_model: str) -> Row:
        res = await self.db.table("memory_items").insert(item).execute()
        row = _one(res.data)
        text = str(row["text"])
        await self.db.table("chunks").insert({
            "corpus": "memory", "production_id": row["production_id"], "source": f"memory:{row['id']}",
            "heading": str(row["kind"]).capitalize(), "context_header": "Production memory", "content": text,
            "content_hash": hashlib.sha256(text.encode()).hexdigest(), "embedding": _vector(embedding),
            "embedding_model": embedding_model if embedding else "", "meta": row.get("source_ref") or {},
        }).execute()
        return row

    async def delete(self, item_id: UUID) -> None:
        await self.db.table("chunks").delete().eq("corpus", "memory").eq("source", f"memory:{item_id}").execute()
        await self.db.table("memory_items").delete().eq("id", str(item_id)).execute()

    async def list(self, production_id: UUID, scene_id: UUID | None = None) -> list[Row]:
        q = self.db.table("memory_items").select("*").eq("production_id", str(production_id))
        if scene_id is not None:
            q = q.eq("scene_id", str(scene_id))
        res = await q.order("created_at", desc=True).execute()
        return _rows(res.data)


_CANON = ("*, current:canon_versions!canon_entities_current_version_fkey"
          "(id, entity_id, version, card, wardrobe_anchor, voice_pin, reference_prompt, reference_assets, source,"
          " created_by, created_at)")


class SupabaseCanon(_Base):
    async def create(self, fields: Row) -> Row:
        res = await self.db.table("canon_entities").insert(fields).execute()
        return _one(res.data)

    async def get(self, production_id: UUID, entity_id: UUID) -> Row | None:
        res = (await self.db.table("canon_entities").select(_CANON).eq("id", str(entity_id))
               .eq("production_id", str(production_id)).limit(1).execute())
        return _first(res.data)

    async def versions(self, entity_id: UUID) -> list[Row]:
        res = (await self.db.table("canon_versions").select("*").eq("entity_id", str(entity_id))
               .order("version", desc=True).execute())
        return _rows(res.data)

    async def update(self, entity_id: UUID, fields: Row) -> Row:
        res = await self.db.table("canon_entities").update(fields).eq("id", str(entity_id)).execute()
        return _one(res.data)

    async def add_version(self, entity_id: UUID, version: Row) -> Row:
        res = await self.db.table("canon_versions").insert(version).execute()
        row = _one(res.data)
        await self.db.table("canon_entities").update({"current_version_id": row["id"]}).eq(
            "id", str(entity_id)).execute()
        return row

    async def list(self, production_id: UUID) -> list[Row]:
        res = await self.db.table("canon_entities").select(_CANON).eq("production_id", str(production_id)).order(
            "code").execute()
        return _rows(res.data)


class SupabaseLooks(_Base):
    async def list_for_production(self, production_id: UUID) -> list[Row]:
        res = await self.db.table("canon_looks").select("*").eq("production_id", str(production_id)).order(
            "created_at").execute()
        return _rows(res.data)

    async def list(self, entity_id: UUID) -> list[Row]:
        res = await self.db.table("canon_looks").select("*").eq("entity_id", str(entity_id)).order(
            "created_at").execute()
        return _rows(res.data)

    async def get(self, entity_id: UUID, look_id: UUID) -> Row | None:
        res = (await self.db.table("canon_looks").select("*").eq("id", str(look_id))
               .eq("entity_id", str(entity_id)).limit(1).execute())
        return _first(res.data)

    async def create(self, fields: Row) -> Row:
        res = await self.db.table("canon_looks").insert(fields).execute()
        return _one(res.data)

    async def update(self, look_id: UUID, fields: Row) -> Row:
        res = await self.db.table("canon_looks").update(fields).eq("id", str(look_id)).execute()
        return _one(res.data)

    async def delete(self, look_id: UUID) -> None:
        await self.db.table("canon_looks").delete().eq("id", str(look_id)).execute()


class SupabaseSceneLooks(_Base):
    async def list(self, scene_id: UUID) -> list[Row]:
        res = await self.db.table("scene_looks").select("*").eq("scene_id", str(scene_id)).execute()
        return _rows(res.data)

    async def choose(self, fields: Row) -> Row:
        res = await self.db.table("scene_looks").upsert(fields, on_conflict="scene_id,entity_id").execute()
        return _one(res.data)

    async def clear(self, scene_id: UUID, entity_id: UUID) -> None:
        await self.db.table("scene_looks").delete().eq("scene_id", str(scene_id)).eq(
            "entity_id", str(entity_id)).execute()


class SupabaseQuestions(_Base):
    async def list(self, production_id: UUID, status: str | None = None) -> list[Row]:
        q = self.db.table("questions").select("*").eq("production_id", str(production_id))
        if status:
            q = q.eq("status", status)
        res = await q.order("created_at").execute()
        return _rows(res.data)

    async def get(self, production_id: UUID, question_id: UUID) -> Row | None:
        res = (await self.db.table("questions").select("*").eq("id", str(question_id))
               .eq("production_id", str(production_id)).limit(1).execute())
        return _first(res.data)

    async def answer(self, question_id: UUID, answer: Row, user_id: UUID) -> Row | None:
        res = (await self.db.table("questions").update({
            "status": "answered", "answer": answer, "answered_by": str(user_id),
            "answered_at": datetime.now(UTC).isoformat()}).eq("id", str(question_id)).eq("status", "open").execute())
        return _first(res.data)

    async def open_count(self, job_id: UUID) -> int:
        res = (await self.db.table("questions").select("id", count="exact")  # type: ignore[arg-type]
               .eq("job_id", str(job_id)).eq("status", "open").execute())
        return res.count or 0


class SupabaseFrames(_Base):
    async def create_many(self, rows: list[Row]) -> None:
        if rows:
            await self.db.table("first_frames").insert(rows).execute()

    async def get(self, production_id: UUID, frame_id: UUID) -> Row | None:
        res = (await self.db.table("first_frames").select("*").eq("id", str(frame_id))
               .eq("production_id", str(production_id)).limit(1).execute())
        return _first(res.data)

    async def list_for_shots(self, shot_ids: list[str]) -> list[Row]:
        if not shot_ids:
            return []
        res = await self.db.table("first_frames").select("*").in_("shot_id", shot_ids).order("created_at").execute()
        return _rows(res.data)

    async def update_many(self, frame_ids: list[str], fields: Row) -> None:
        if frame_ids:
            await self.db.table("first_frames").update(fields).in_("id", frame_ids).execute()

    async def accept(self, shot_id: UUID, frame_id: UUID, user_id: UUID) -> bool:
        # Clear the old choice first: one accepted frame per shot is a unique index.
        await (self.db.table("first_frames").update({"accepted_at": None, "accepted_by": None})
               .eq("shot_id", str(shot_id)).neq("id", str(frame_id)).not_.is_("accepted_at", "null").execute())
        try:
            res = await (self.db.table("first_frames").update({"accepted_at": datetime.now(UTC).isoformat(),
                                                               "accepted_by": str(user_id)})
                         .eq("id", str(frame_id)).eq("status", "done").execute())
        except Exception:  # a concurrent accept of another frame took the slot
            _logger.warning("accept raced shot=%s frame=%s", shot_id, frame_id, exc_info=True)
            return False
        return bool(_rows(res.data))

    async def unaccept(self, frame_id: UUID) -> None:
        await self.db.table("first_frames").update({"accepted_at": None, "accepted_by": None}).eq(
            "id", str(frame_id)).execute()


class SupabasePrompts(_Base):
    async def latest_for_shots(self, shot_ids: list[str]) -> dict[str, Row]:
        if not shot_ids:
            return {}
        res = (await self.db.table("video_prompts").select("*").in_("shot_id", shot_ids)
               .order("version", desc=True).execute())
        out: dict[str, Row] = {}
        for row in _rows(res.data):
            out.setdefault(str(row["shot_id"]), row)
        return out

    async def list(self, shot_id: UUID) -> list[Row]:
        res = (await self.db.table("video_prompts").select("*").eq("shot_id", str(shot_id))
               .order("version", desc=True).execute())
        return _rows(res.data)


class SupabaseTakes(_Base):
    async def create(self, row: Row) -> Row:
        res = await self.db.table("takes").insert(row).execute()
        return _one(res.data)

    async def get(self, production_id: UUID, take_id: UUID) -> Row | None:
        res = (await self.db.table("takes").select("*").eq("id", str(take_id))
               .eq("production_id", str(production_id)).limit(1).execute())
        return _first(res.data)

    async def list_for_shots(self, shot_ids: list[str]) -> list[Row]:
        if not shot_ids:
            return []
        res = await self.db.table("takes").select("*").in_("shot_id", shot_ids).order("created_at").execute()
        return _rows(res.data)

    async def update(self, take_id: UUID, fields: Row) -> Row:
        res = await self.db.table("takes").update(fields).eq("id", str(take_id)).execute()
        return _one(res.data)

    async def accept(self, shot_id: UUID, take_id: UUID, user_id: UUID) -> bool:
        # Release the old choice first: one accepted take per shot is a unique index.
        await (self.db.table("takes").update({"status": "uploaded", "accepted_at": None, "accepted_by": None})
               .eq("shot_id", str(shot_id)).eq("status", "accepted").neq("id", str(take_id)).execute())
        try:
            res = await (self.db.table("takes").update({
                "status": "accepted", "accepted_at": datetime.now(UTC).isoformat(), "accepted_by": str(user_id),
                "reason": None}).eq("id", str(take_id)).execute())
        except Exception:
            _logger.warning("take accept raced shot=%s take=%s", shot_id, take_id, exc_info=True)
            return False
        return bool(_rows(res.data))


async def build_supabase_repos(url: str, service_role_key: str) -> Repos:
    db = await acreate_client(url, service_role_key)
    # Count REST calls per API request (see api/observability.py).
    db.postgrest.session.event_hooks.setdefault("request", []).append(count_db_call)
    return Repos(
        profiles=SupabaseProfiles(db),
        productions=SupabaseProductions(db),
        members=SupabaseMembers(db),
        invitations=SupabaseInvitations(db),
        auth_admin=SupabaseAuthAdmin(db),
        audit=SupabaseAudit(db),
        jobs=SupabaseJobs(db),
        documents=SupabaseDocuments(db),
        storage=SupabaseStorage(db),
        search=SupabaseSearch(db),
        usage=SupabaseUsage(db),
        episodes=SupabaseEpisodes(db),
        scenes=SupabaseScenes(db),
        shots=SupabaseShots(db),
        lines=SupabaseLines(db),
        canon=SupabaseCanon(db),
        looks=SupabaseLooks(db),
        scene_looks=SupabaseSceneLooks(db),
        questions=SupabaseQuestions(db),
        personas=SupabasePersonas(db),
        board=SupabaseBoard(db),
        threads=SupabaseThreads(db),
        messages=SupabaseMessages(db),
        memory=SupabaseMemory(db),
        frames=SupabaseFrames(db),
        prompts=SupabasePrompts(db),
        takes=SupabaseTakes(db),
    )
