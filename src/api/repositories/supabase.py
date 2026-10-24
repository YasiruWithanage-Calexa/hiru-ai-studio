"""Supabase-backed repositories (supabase-py async client, service role)."""
from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from supabase import AsyncClient, acreate_client

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


class SupabaseProfiles(_Base):
    async def get(self, user_id: UUID) -> Row | None:
        res = await self.db.table("profiles").select("*").eq("id", str(user_id)).limit(1).execute()
        return _first(res.data)

    async def get_by_email(self, email: str) -> Row | None:
        res = await self.db.table("profiles").select("*").eq("email", email.lower()).limit(1).execute()
        return _first(res.data)

    async def list(self) -> list[Row]:
        res = await self.db.table("profiles").select("*").order("display_name").execute()
        return _rows(res.data)

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

    async def list(self, thread_id: UUID, limit: int = 100) -> list[Row]:
        res = (await self.db.table("chat_messages").select("*").eq("thread_id", str(thread_id))
               .order("created_at", desc=True).limit(limit).execute())
        return _rows(res.data)[::-1]


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
          "(id, entity_id, version, card, wardrobe_anchor, voice_pin, reference_prompt, source, created_by,"
          " created_at)")


class SupabaseCanon(_Base):
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
        documents=SupabaseDocuments(db),
        storage=SupabaseStorage(db),
        search=SupabaseSearch(db),
        usage=SupabaseUsage(db),
        episodes=SupabaseEpisodes(db),
        scenes=SupabaseScenes(db),
        shots=SupabaseShots(db),
        lines=SupabaseLines(db),
        canon=SupabaseCanon(db),
        questions=SupabaseQuestions(db),
        personas=SupabasePersonas(db),
        board=SupabaseBoard(db),
        threads=SupabaseThreads(db),
        messages=SupabaseMessages(db),
        memory=SupabaseMemory(db),
    )
