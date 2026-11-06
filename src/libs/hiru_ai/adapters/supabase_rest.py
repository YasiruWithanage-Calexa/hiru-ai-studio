"""Supabase PostgREST over HTTP with the service role: the adapters behind the data ports.

Merged from the `runtime/rest.py` and `runtime/store.py` each function vendors today (they differ only in what each
needs): one `Rest` client, and one small class per port in `core/ports.py`. Only the edge (a function handler, the API,
the CLI) imports this module; a part asks the run for its port.

The row shapes and column lists are the services' own, so a part behaves the same against either.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx

from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.ports import Row
from hiru_ai.core.settings import AISettings, get_settings
from hiru_ai.core.staging import StagedCards
from hiru_ai.core.telemetry import enable_tracing
from hiru_ai.core.usage import UsageSink

_log = logging.getLogger("hiru_ai.adapters.supabase")
INSERT_BATCH = 100
_BATCH = 200
# Picture-sized bodies on a slow link need a long read/write; a dead host should still fail fast.
TIMEOUT = httpx.Timeout(60.0, connect=10.0, write=120.0)

CANON_FULL = ("id,kind,code,name,aliases,core,locked,current_version_id,"
              "current:canon_versions!canon_entities_current_version_fkey"
              "(id,version,card,card_hash,source,wardrobe_anchor,voice_pin,reference_prompt,reference_assets)")
SCENE_WITH_EPISODE = "*,episode:episodes(number,title,synopsis)"


def vector(values: list[float] | None) -> str | None:
    """A pgvector literal for an RPC argument."""
    return None if values is None else "[" + ",".join(f"{v:.7g}" for v in values) + "]"


def same_keys(rows: list[Row]) -> list[Row]:
    """PostgREST takes one set of keys per bulk write. A translated line carries `source_text` / `source_lang`
    (plan/2026-11-01c) and an untranslated one does not, so a key some rows lack is written as null on the others."""
    keys = list(dict.fromkeys(k for row in rows for k in row))
    return [{k: row.get(k) for k in keys} for row in rows]


def _ok(r: httpx.Response) -> None:
    """raise_for_status, with what PostgREST said: a bare "400 Bad Request" hides a missing column or a bad value."""
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise httpx.HTTPStatusError(f"{error}\nSupabase said: {r.text[:500]}",
                                    request=error.request, response=error.response) from None


class Rest:
    def __init__(self, url: str, service_role_key: str, client: httpx.Client | None = None) -> None:
        base = url.rstrip("/")
        self.rest = f"{base}/rest/v1"
        self.storage = f"{base}/storage/v1"
        self.client = client or httpx.Client(timeout=TIMEOUT)
        self.headers = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}",
                        "Content-Type": "application/json"}

    def select(self, table: str, params: dict[str, str]) -> list[Row]:
        r = self.client.get(f"{self.rest}/{table}", headers=self.headers, params=params)
        _ok(r)
        return list(r.json())

    def first(self, table: str, params: dict[str, str]) -> Row | None:
        rows = self.select(table, {**params, "limit": "1"})
        return rows[0] if rows else None

    def insert(self, table: str, rows: list[Row]) -> None:
        for i in range(0, len(rows), _BATCH):
            _ok(self.client.post(f"{self.rest}/{table}", headers=self.headers, json=rows[i: i + _BATCH]))

    def upsert(self, table: str, rows: list[Row], on_conflict: str = "id") -> None:
        """Insert or merge. Every row in one call must have the same keys (PostgREST rule)."""
        headers = {**self.headers, "Prefer": "resolution=merge-duplicates"}
        for i in range(0, len(rows), _BATCH):
            _ok(self.client.post(f"{self.rest}/{table}", headers=headers, params={"on_conflict": on_conflict},
                                 json=rows[i: i + _BATCH]))

    def patch(self, table: str, params: dict[str, str], fields: Row) -> None:
        _ok(self.client.patch(f"{self.rest}/{table}", headers=self.headers, params=params, json=fields))

    def claim(self, table: str, params: dict[str, str], fields: Row) -> list[Row]:
        """PATCH … WHERE params, returning the rows changed. Zero rows: someone else has it."""
        headers = {**self.headers, "Prefer": "return=representation"}
        r = self.client.patch(f"{self.rest}/{table}", headers=headers, params=params, json=fields)
        _ok(r)
        return list(r.json())

    def delete(self, table: str, params: dict[str, str]) -> None:
        _ok(self.client.delete(f"{self.rest}/{table}", headers=self.headers, params=params))

    def rpc(self, function: str, args: Row) -> list[Row]:
        r = self.client.post(f"{self.rest}/rpc/{function}", headers=self.headers, json=args)
        _ok(r)
        return list(r.json())


class SupabaseScenes:
    """`SceneStore`: a production's scenes, lines and shots, and the two ways a plan is saved."""

    def __init__(self, rest: Rest) -> None:
        self.rest = rest

    def production(self, production_id: UUID) -> Row | None:
        return self.rest.first("productions", {"id": f"eq.{production_id}",
                                               "select": "id,title,orientation,settings,summary"})

    def scenes(self, production_id: UUID, scene_ids: list[str] | None) -> list[Row]:
        params = {"production_id": f"eq.{production_id}", "select": SCENE_WITH_EPISODE, "order": "episode_id,number"}
        if scene_ids is not None:
            if not scene_ids:
                return []
            params["id"] = f"in.({','.join(str(i) for i in scene_ids)})"
        return self.rest.select("scenes", params)

    def lines(self, scene_id: UUID | str) -> list[Row]:
        return self.rest.select("dialogue_lines", {"scene_id": f"eq.{scene_id}", "select": "*", "order": "ord"})

    def shots(self, scene_id: UUID | str) -> list[Row]:
        return self.rest.select("shots", {"scene_id": f"eq.{scene_id}", "select": "*", "order": "number"})

    def canon(self, production_id: UUID) -> list[Row]:
        return self.rest.select("canon_entities", {"production_id": f"eq.{production_id}", "order": "code",
                                                   "select": CANON_FULL})

    def save_plan(self, scene_id: UUID | str, shots: list[Row], removed: list[str], lines: list[Row],
                  scene_fields: Row, removed_lines: list[str] | None = None) -> None:
        """Shots keep their ids (frames and prompts hang off them); numbering is checked at the end of the
        statement (deferred unique), so one upsert can renumber them. Lines a script change removed go first, and
        the scene's script last, once every line it names exists."""
        if removed_lines:
            self.rest.delete("dialogue_lines", {"id": f"in.({','.join(removed_lines)})"})
        if removed:
            self.rest.delete("shots", {"id": f"in.({','.join(removed)})"})
        if shots:
            self.rest.upsert("shots", shots)
        if lines:
            self.rest.upsert("dialogue_lines", same_keys(lines))
        self.rest.patch("scenes", {"id": f"eq.{scene_id}"}, scene_fields)

    def replace_shots(self, scene_id: UUID | str, shots: list[Row], lines: list[Row], scene_fields: Row) -> None:
        """Delete the scene's shots, write the new ones, re-bind its lines, update the scene. Re-running it gives
        the same rows (idempotent for Cloud Tasks re-delivery)."""
        self.rest.delete("shots", {"scene_id": f"eq.{scene_id}"})
        if shots:
            self.rest.insert("shots", shots)
        if lines:
            self.rest.upsert("dialogue_lines", same_keys(lines))
        self.rest.patch("scenes", {"id": f"eq.{scene_id}"}, scene_fields)

    def save_design(self, shot_id: str, ir: Row, design: Row) -> None:
        self.rest.patch("shots", {"id": f"eq.{shot_id}"}, {"ir": ir, "design": design})

    def add_prompt(self, row: Row) -> None:
        """A new prompt version; the shot moves to `prompt`. A version number taken meanwhile by another job is
        retried once with the next number."""
        try:
            self.rest.insert("video_prompts", [row])
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 409:
                raise
            last = self.rest.first("video_prompts", {"shot_id": f"eq.{row['shot_id']}", "select": "version",
                                                     "order": "version.desc"})
            row = {**row, "version": (int(last["version"]) if last else 0) + 1}
            self.rest.insert("video_prompts", [row])
        self.rest.patch("shots", {"id": f"eq.{row['shot_id']}"}, {"status": "prompt"})

    def latest_prompts(self, shot_ids: list[str]) -> dict[str, Row]:
        if not shot_ids:
            return {}
        rows = self.rest.select("video_prompts", {
            "shot_id": f"in.({','.join(str(s) for s in shot_ids)})", "order": "shot_id,version.desc",
            "select": "shot_id,version,sections,prose,model,checks,pins,frame_id,camera,created_at"})
        out: dict[str, Row] = {}
        for row in rows:  # newest first within a shot
            out.setdefault(str(row["shot_id"]), row)
        return out


class SupabaseCanon:
    """`CanonStore`: entities with their current version."""

    def __init__(self, rest: Rest) -> None:
        self.rest = rest

    def entities(self, production_id: UUID) -> list[Row]:
        return self.rest.select("canon_entities", {"production_id": f"eq.{production_id}", "order": "code",
                                                   "select": CANON_FULL})

    def create_entity(self, entity: Row, version: Row) -> None:
        self.rest.insert("canon_entities", [entity])
        self.rest.insert("canon_versions", [version])
        self.rest.patch("canon_entities", {"id": f"eq.{entity['id']}"}, {"current_version_id": version["id"]})

    def add_version(self, entity_id: str, version: Row, fields: Row) -> None:
        self.rest.insert("canon_versions", [version])
        self.rest.patch("canon_entities", {"id": f"eq.{entity_id}"}, {**fields, "current_version_id": version["id"]})

    def update_entity(self, entity_id: str, fields: Row) -> None:
        self.rest.patch("canon_entities", {"id": f"eq.{entity_id}"}, fields)

    def looks(self, production_id: UUID) -> list[Row]:
        return self.rest.select("canon_looks", {"production_id": f"eq.{production_id}", "order": "created_at",
                                                "select": "id,entity_id,name,ranges,outfit,hair,makeup,accessories,"
                                                          "status"})


class SupabaseStructure:
    """`StructureStore`: episodes and scenes as the structure build writes them."""

    def __init__(self, rest: Rest) -> None:
        self.rest = rest

    def episodes(self, production_id: UUID) -> list[Row]:
        return self.rest.select("episodes", {"production_id": f"eq.{production_id}", "select": "id,number,status"})

    def scene_headers(self, production_id: UUID) -> list[Row]:
        return self.rest.select("scenes", {"production_id": f"eq.{production_id}",
                                           "select": "id,episode_id,number,status,envelope_s,script_version"})

    def upsert_episodes(self, rows: list[Row]) -> None:
        self.rest.upsert("episodes", rows)

    def write_scene(self, scene: Row, lines: list[Row]) -> None:
        """Replace one scene's content: its shots and lines go (they point at the old script)."""
        self.rest.upsert("scenes", [scene])
        self.rest.delete("shots", {"scene_id": f"eq.{scene['id']}"})
        self.rest.delete("dialogue_lines", {"scene_id": f"eq.{scene['id']}"})
        if lines:
            self.rest.insert("dialogue_lines", lines)

    def delete_scenes(self, scene_ids: list[str]) -> None:
        if scene_ids:
            self.rest.delete("scenes", {"id": f"in.({','.join(scene_ids)})"})

    def upsert_questions(self, rows: list[Row]) -> None:
        if rows:
            self.rest.upsert("questions", rows)

    def answers(self, job_id: UUID) -> list[Row]:
        return self.rest.select("questions", {"job_id": f"eq.{job_id}", "select": "key,status,answer"})

    def earlier_answers(self, production_id: UUID) -> list[Row]:
        return self.rest.select("questions", {"production_id": f"eq.{production_id}", "status": "eq.answered",
                                              "select": "key,answer", "order": "answered_at"})

    def entities_with_looks(self, production_id: UUID) -> set[str]:
        rows = self.rest.select("canon_looks", {"production_id": f"eq.{production_id}", "select": "entity_id"})
        return {str(r["entity_id"]) for r in rows}

    def create_looks(self, rows: list[Row]) -> None:
        if rows:
            self.rest.insert("canon_looks", rows)

    def open_questions(self, production_id: UUID) -> list[Row]:
        return self.rest.select("questions", {"production_id": f"eq.{production_id}", "status": "eq.open",
                                              "select": "key,scope,title,body", "order": "created_at"})


class SupabaseSplit:
    """`SplitStore`: what the splitter reads around a scene, and an episode's status."""

    def __init__(self, rest: Rest) -> None:
        self.rest = rest

    def episodes(self, production_id: UUID) -> list[Row]:
        return self.rest.select("episodes", {"production_id": f"eq.{production_id}",
                                             "select": "id,number,title,synopsis,status", "order": "number"})

    def neighbours(self, production_id: UUID) -> list[Row]:
        return self.rest.select("scenes", {"production_id": f"eq.{production_id}",
                                           "select": "id,episode_id,number,heading,title",
                                           "order": "episode_id,number"})

    def characters(self, production_id: UUID) -> list[Row]:
        return self.rest.select("canon_entities", {
            "production_id": f"eq.{production_id}", "kind": "eq.character",
            "select": "id,code,name,current:canon_versions!canon_entities_current_version_fkey(card)",
            "order": "code"})

    def locations(self, production_id: UUID) -> list[Row]:
        """The production's places, for the staging map's spots."""
        return self.rest.select("canon_entities", {
            "production_id": f"eq.{production_id}", "kind": "eq.location",
            "select": "id,name,current:canon_versions!canon_entities_current_version_fkey(card)", "order": "code"})

    def scene_status(self, production_id: UUID) -> list[Row]:
        return self.rest.select("scenes", {"production_id": f"eq.{production_id}", "select": "episode_id,status"})

    def set_episode_status(self, episode_id: str, status: str) -> None:
        self.rest.patch("episodes", {"id": f"eq.{episode_id}"}, {"status": status})


class SupabaseDirector:
    """`DirectorStore`: the scene as the director reads it, the board and the thread, the pending action, the memory."""

    def __init__(self, rest: Rest) -> None:
        self.rest = rest

    def scene(self, production_id: UUID, scene_id: UUID) -> Row | None:
        return self.rest.first("scenes", {"id": f"eq.{scene_id}", "production_id": f"eq.{production_id}",
                                          "select": "*,episode:episodes(number,title)"})

    def board(self, production_id: UUID) -> list[Row]:
        return self.rest.select("production_director_board", {
            "production_id": f"eq.{production_id}",
            "select": "seat,persona:director_personas(id,name,initials,specialty,style_note,charter)"})

    def default_persona(self) -> Row | None:
        return self.rest.first("director_personas", {"active": "eq.true", "slug": "eq.classic-teledrama",
                                                     "select": "id,name,initials,specialty,style_note,charter"})

    def messages(self, thread_id: UUID, limit: int = 12) -> list[Row]:
        rows = self.rest.select("chat_messages", {"thread_id": f"eq.{thread_id}",
                                                  "select": "id,kind,speaker,text,blocks",
                                                  "order": "created_at.desc", "limit": str(limit)})
        return rows[::-1]

    def message(self, message_id: UUID | str) -> Row | None:
        return self.rest.first("chat_messages", {"id": f"eq.{message_id}", "select": "id,kind,speaker,text,blocks"})

    def open_pending(self, thread_id: UUID | str) -> Row | None:
        """The thread's open pending action; at most one is open."""
        return self.rest.first("pending_actions", {"thread_id": f"eq.{thread_id}", "status": "eq.open",
                                                   "order": "created_at.desc", "select": "*"})

    def add_pending(self, row: Row) -> None:
        self.rest.insert("pending_actions", [row])

    def close_pending(self, thread_id: UUID | str, status: str) -> None:
        self.rest.patch("pending_actions", {"thread_id": f"eq.{thread_id}", "status": "eq.open"},
                        {"status": status, "closed_at": datetime.now(UTC).isoformat()})

    def set_blocks(self, message_id: UUID | str, blocks: list[Row]) -> None:
        self.rest.patch("chat_messages", {"id": f"eq.{message_id}"}, {"blocks": blocks})

    def memory(self, production_id: UUID, limit: int = 20) -> list[Row]:
        return self.rest.select("memory_items", {"production_id": f"eq.{production_id}", "select": "kind,text",
                                                 "order": "created_at.desc", "limit": str(limit)})

    def open_questions(self, production_id: UUID) -> list[Row]:
        return self.rest.select("questions", {"production_id": f"eq.{production_id}", "status": "eq.open",
                                              "select": "scope,title,body"})

    def ready_documents(self, production_id: UUID) -> list[Row]:
        return self.rest.select("documents", {"production_id": f"eq.{production_id}", "status": "eq.ready",
                                              "select": "id,filename"})

    def search(self, *, query: str, embedding: list[float] | None, production_id: UUID, document_ids: list[str],
               k: int = 6) -> list[Row]:
        return self.rest.rpc("match_chunks", {
            "query_text": query, "query_embedding": vector(embedding), "p_production_id": str(production_id),
            "p_corpora": ["production_docs", "memory"], "p_document_ids": document_ids, "match_count": k})

    def add_message(self, row: Row) -> None:
        self.rest.insert("chat_messages", [row])

    def add_memory(self, item: Row, embedding: list[float] | None, model: str) -> None:
        self.rest.insert("memory_items", [item])
        text = str(item["text"])
        self.rest.insert("chunks", [_with_vector({
            "corpus": "memory", "production_id": item["production_id"], "source": f"memory:{item['id']}",
            "heading": item["kind"].capitalize(), "context_header": "Production memory", "content": text,
            "content_hash": hashlib.sha256(text.encode()).hexdigest(), "embedding": embedding,
            "embedding_model": model if embedding else "", "meta": json.loads(json.dumps(item["source_ref"]))})])

    def audit(self, row: Row) -> None:
        try:
            self.rest.insert("audit_log", [row])
        except httpx.HTTPError:
            pass  # the audit trail never fails the change it records


class SupabaseProducer:
    """`ProducerStore`: what the producer reads around a scene, and the intents and coverage it saves."""

    _PERSONA = "id,name,specialty,style_note,charter"

    def __init__(self, rest: Rest) -> None:
        self.rest = rest

    def neighbours(self, scene: Row) -> tuple[Row | None, Row | None]:
        number = int(scene.get("number") or 0)
        rows = self.rest.select("scenes", {"episode_id": f"eq.{scene.get('episode_id')}",
                                           "number": f"in.({number - 1},{number + 1})",
                                           "select": "number,title,heading,script"})
        by_number = {int(r["number"]): r for r in rows}
        return by_number.get(number - 1), by_number.get(number + 1)

    def shot_scenes(self, production_id: UUID, shot_ids: list[str]) -> list[str]:
        if not shot_ids:
            return []
        rows = self.rest.select("shots", {"production_id": f"eq.{production_id}",
                                          "id": f"in.({','.join(shot_ids)})", "select": "scene_id"})
        return list(dict.fromkeys(str(r["scene_id"]) for r in rows))

    def lead_persona(self, production_id: UUID) -> Row | None:
        seat = self.rest.first("production_director_board", {
            "production_id": f"eq.{production_id}", "seat": "eq.lead",
            "select": f"persona:director_personas({self._PERSONA})"})
        if seat and seat.get("persona"):
            return dict(seat["persona"])
        return self.rest.first("director_personas", {"slug": "eq.classic-teledrama", "select": self._PERSONA})

    def accepted_frames(self, shot_ids: list[str]) -> dict[str, Row]:
        if not shot_ids:
            return {}
        rows = self.rest.select("first_frames", {"shot_id": f"in.({','.join(shot_ids)})",
                                                 "accepted_at": "not.is.null", "select": "id,shot_id,pins"})
        return {str(r["shot_id"]): r for r in rows}

    def last_prompt_version(self, shot_id: str) -> int:
        row = self.rest.first("video_prompts", {"shot_id": f"eq.{shot_id}", "select": "version",
                                                "order": "version.desc"})
        return int(row["version"]) if row else 0

    def save_intent(self, shot_id: str, intent: Row) -> None:
        self._save_optional("shots", shot_id, {"intent": intent})

    def save_coverage(self, scene_id: str, coverage: Row) -> None:
        self._save_optional("scenes", scene_id, {"coverage": coverage})

    def _save_optional(self, table: str, row_id: str, fields: Row) -> None:
        """A database still on schema v8 has no `intent` / `coverage` column. The design still runs on what this job
        wrote in memory; it is just not kept (Database/README.md, v8 -> v9)."""
        try:
            self.rest.patch(table, {"id": f"eq.{row_id}"}, fields)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 400:
                raise
            _log.warning("%s.%s could not be saved (schema v8?)", table, ",".join(fields))

    def audit(self, row: Row) -> None:
        try:
            self.rest.insert("audit_log", [row])
        except httpx.HTTPError:
            pass  # the audit trail never fails the change it records


class SupabaseFrames:
    """`FrameStore`: `first_frames` and what a frame reads about its shot, canon and looks."""

    def __init__(self, rest: Rest) -> None:
        self.rest = rest

    def frames(self, production_id: UUID, frame_ids: list[str]) -> list[Row]:
        if not frame_ids:
            return []
        return self.rest.select("first_frames", {"production_id": f"eq.{production_id}",
                                                 "id": f"in.({','.join(frame_ids)})", "select": "*",
                                                 "order": "created_at"})

    def shot(self, shot_id: str) -> Row | None:
        return self.rest.first("shots", {"id": f"eq.{shot_id}", "select": "*"})

    def scene(self, scene_id: str) -> Row | None:
        return self.rest.first("scenes", {"id": f"eq.{scene_id}", "select": "*"})

    def look(self, look_id: str) -> Row | None:
        return self.rest.first("canon_looks", {"id": f"eq.{look_id}", "select": "*"})

    def looks(self, production_id: UUID) -> list[Row]:
        return self.rest.select("canon_looks", {"production_id": f"eq.{production_id}", "select": "*",
                                                "order": "created_at"})

    def scene_looks(self, scene_id: str) -> list[Row]:
        return self.rest.select("scene_looks", {"scene_id": f"eq.{scene_id}", "select": "entity_id,look_id"})

    def episode_number(self, episode_id: str) -> int | None:
        row = self.rest.first("episodes", {"id": f"eq.{episode_id}", "select": "number"})
        return int(row["number"]) if row else None

    def frame_status(self, production_id: UUID, shot_ids: list[str] | None = None,
                     codes: list[str] | None = None) -> Row:
        """Counts and states only: a storage path never leaves this method (CLAUDE.md "Files")."""
        frames: list[Row] = []
        if shot_ids:
            rows = self.rest.select("first_frames", {
                "production_id": f"eq.{production_id}", "shot_id": f"in.({','.join(shot_ids)})",
                "select": "id,shot_id,status,accepted_at,pins,error,created_at", "order": "created_at"})
            frames = [{"id": r["id"], "shot_id": r["shot_id"], "status": r["status"],
                       "accepted": bool(r.get("accepted_at")), "pins": r.get("pins") or {}, "error": r.get("error"),
                       "created_at": r.get("created_at")} for r in rows]
        sheets: list[Row] = []
        if codes:
            entities = self.rest.select("canon_entities", {
                "production_id": f"eq.{production_id}", "code": f"in.({','.join(codes)})", "select": CANON_FULL})
            looks = self.rest.select("canon_looks", {
                "production_id": f"eq.{production_id}", "select": "entity_id,name,status,sheet_assets,ranges",
                "order": "created_at"})
            for e in entities:
                own = [lk for lk in looks if str(lk["entity_id"]) == str(e["id"])]
                sheets.append({"code": e["code"], "name": e["name"], "kind": e["kind"],
                               "sheets": len((e.get("current") or {}).get("reference_assets") or []),
                               "looks": [{"name": lk["name"], "status": lk["status"],
                                          "sheets": len(lk.get("sheet_assets") or []), "ranges": lk.get("ranges") or []}
                                         for lk in own]})
        return {"frames": frames, "sheets": sheets}

    def claim_frame(self, frame_id: str) -> bool:
        return bool(self.rest.claim("first_frames", {"id": f"eq.{frame_id}", "status": "eq.queued"},
                                    {"status": "running"}))

    def finish_frame(self, frame_id: str, fields: Row) -> None:
        try:
            self.rest.patch("first_frames", {"id": f"eq.{frame_id}"}, fields)
        except httpx.HTTPStatusError as exc:
            # A database still on schema v8 has no `checks` column: the frame matters more than its checks, so it is
            # recorded without them (Database/README.md, v8 -> v9).
            if "checks" not in fields or exc.response.status_code != 400:
                raise
            _log.warning("first_frames.checks missing (schema v8?); frame %s saved without checks", frame_id)
            rest = {k: v for k, v in fields.items() if k != "checks"}
            self.rest.patch("first_frames", {"id": f"eq.{frame_id}"}, rest)

    def add_reference_asset(self, version_id: str, assets: list[Any]) -> None:
        self.rest.patch("canon_versions", {"id": f"eq.{version_id}"}, {"reference_assets": assets})

    def finish_look_sheet(self, look_id: str, assets: list[Any]) -> None:
        """A new sheet is not the one a person approved: the look goes back to draft."""
        self.rest.patch("canon_looks", {"id": f"eq.{look_id}"}, {"sheet_assets": assets, "status": "draft"})

    def audit(self, row: Row) -> None:
        try:
            self.rest.insert("audit_log", [row])
        except httpx.HTTPError:
            pass


class SupabaseDocs:
    """`DocStore`: ready documents and the text extracted from them."""

    BUCKET = "documents"

    def __init__(self, rest: Rest, files: Any) -> None:
        self.rest = rest
        self.files = files

    def documents(self, production_id: UUID) -> list[Row]:
        return self.rest.select("documents", {
            "production_id": f"eq.{production_id}", "status": "eq.ready",
            "select": "id,filename,detected_role,confirmed_role,text_path,created_at", "order": "created_at"})

    def text(self, path: str) -> str:
        return bytes(self.files.download(self.BUCKET, path)).decode("utf-8")

    def get_document(self, document_id: UUID) -> Row | None:
        return self.rest.first("documents", {"id": f"eq.{document_id}", "select": "*"})

    def update_document(self, document_id: UUID, fields: Row) -> None:
        self.rest.patch("documents", {"id": f"eq.{document_id}"}, fields)

    def existing_embeddings(self, document_id: UUID) -> dict[str, tuple[list[float], str]]:
        out: dict[str, tuple[list[float], str]] = {}
        for row in self.rest.select("chunks", {"document_id": f"eq.{document_id}", "embedding": "not.is.null",
                                               "select": "content_hash,embedding,embedding_model"}):
            emb = row["embedding"]
            out[row["content_hash"]] = (json.loads(emb) if isinstance(emb, str) else emb, row["embedding_model"])
        return out

    def replace_chunks(self, document_id: UUID, rows: list[Row]) -> None:
        self.rest.delete("chunks", {"document_id": f"eq.{document_id}"})
        for i in range(0, len(rows), INSERT_BATCH):
            self.rest.insert("chunks", [_with_vector(r) for r in rows[i: i + INSERT_BATCH]])


class SupabaseMemory:
    """`MemoryStore`: the entries of `production_memory`. Needs the table (schema v12); a read that fails because it is
    missing is handled by the caller (`core.memory.entries`, the ingest), never here."""

    COLUMNS = "id,document_id,topic,applies_to,says,quote,strength,status,source"

    def __init__(self, rest: Rest) -> None:
        self.rest = rest

    def entries(self, production_id: UUID) -> list[Row]:
        return self.rest.select("production_memory", {"production_id": f"eq.{production_id}", "select": self.COLUMNS,
                                                      "order": "created_at,id"})

    def replace_from(self, production_id: UUID, document_id: UUID, entries: list[Row]) -> None:
        from hiru_ai.core import memory

        mine = self.rest.select("production_memory", {"document_id": f"eq.{document_id}", "select": self.COLUMNS})
        kept = [r for r in mine if not memory.is_reader_draft(r)]
        self.rest.delete("production_memory", {"document_id": f"eq.{document_id}", "source": "eq.reader",
                                               "status": "eq.draft"})
        rows = [{"production_id": str(production_id), "document_id": str(document_id), "status": "draft",
                 "source": "reader", **{k: e[k] for k in ("topic", "applies_to", "says", "quote", "strength")}}
                for e in memory.fresh(kept, entries)]
        if rows:
            self.rest.insert("production_memory", rows)

    def upsert(self, row: Row) -> None:
        if row.get("id"):
            self.rest.upsert("production_memory", [{**row, "updated_at": datetime.now(UTC).isoformat()}])
        else:
            self.rest.insert("production_memory", [row])


class SupabaseSearch:
    """`Search`: `match_chunks` (hybrid keyword + vector) and `match_craft_techniques`."""

    def __init__(self, rest: Rest) -> None:
        self.rest = rest

    def chunks(self, *, query: str, embedding: list[float] | None, production_id: UUID, corpora: list[str],
               document_ids: list[str] | None, k: int) -> list[Row]:
        return self.rest.rpc("match_chunks", {
            "query_text": query, "query_embedding": vector(embedding), "p_production_id": str(production_id),
            "p_corpora": corpora, "p_document_ids": document_ids, "match_count": k})

    def techniques(self, query: str, embedding: list[float] | None, k: int = 4) -> list[Row]:
        """Intent → technique lookup. Absent-safe: [] on any failure."""
        try:
            return self.rest.rpc("match_craft_techniques", {
                "query_text": query, "query_embedding": vector(embedding), "match_domain": "",
                "match_categories": None, "match_count": k})
        except httpx.HTTPError:
            _log.warning("technique lookup failed; answering with none", exc_info=True)
            return []

    def memory(self, query: str, embedding: list[float] | None, production_id: UUID, k: int = 6) -> list[Row]:
        return self.rest.rpc("match_chunks", {
            "query_text": query, "query_embedding": vector(embedding), "p_production_id": str(production_id),
            "p_corpora": ["memory"], "p_document_ids": None, "match_count": k})


class SupabaseKnowledge:
    """`KnowledgeStore`: `chunks` rows of the craft corpus and the `craft_techniques` table."""

    def __init__(self, rest: Rest) -> None:
        self.rest = rest

    def embeddings(self, corpus: str, source_prefix: str) -> dict[str, Any]:
        rows = self.rest.select("chunks", {
            "corpus": f"eq.{corpus}", "source": f"like.{source_prefix}*", "embedding": "not.is.null",
            "select": "content_hash,embedding"})
        return {r["content_hash"]: r["embedding"] for r in rows}

    def replace_chunks(self, corpus: str, source_prefix: str, rows: list[Row]) -> None:
        self.rest.delete("chunks", {"corpus": f"eq.{corpus}", "source": f"like.{source_prefix}*"})
        self.rest.insert("chunks", [_with_vector(r) for r in rows])

    def replace_techniques(self, rows: list[Row]) -> None:
        self.rest.delete("craft_techniques", {"id": "gte.0"})
        self.rest.insert("craft_techniques", [_with_vector(r) for r in rows])


def _with_vector(row: Row) -> Row:
    """An embedding as a list becomes a pgvector literal; one read back from the table already is."""
    emb = row.get("embedding")
    return {**row, "embedding": vector(emb) if isinstance(emb, list) else emb}


def usage_sink(rest: Rest) -> UsageSink:
    """A `token_usage` writer. Accounting must never fail the work it accounts for. A row carries the per-component
    columns of schema v10 only when the run asked for them (`RunContext.usage_detail`, from `USAGE_DETAIL=true` once the
    database has them): PostgREST refuses a row that names a column the table lacks."""

    def write(row: Row) -> None:
        try:
            rest.insert("token_usage", [row])
        except httpx.HTTPError:
            _log.warning("token_usage row not written", exc_info=True)

    return write


def build_knowledge_store(settings: AISettings | None = None, *,
                          client: httpx.Client | None = None) -> SupabaseKnowledge:
    settings = settings or get_settings()
    return SupabaseKnowledge(Rest(settings.supabase.url, settings.supabase.service_role_key.get_secret_value(), client))


def _ports(rest: Rest, jobs: Any = None) -> Ports:
    from hiru_ai.adapters.storage import SupabaseFiles

    files = SupabaseFiles(rest)
    return Ports(scenes=SupabaseScenes(rest), canon=SupabaseCanon(rest), structure=SupabaseStructure(rest),
                 frames=SupabaseFrames(rest), split=SupabaseSplit(rest), producer=SupabaseProducer(rest),
                 director=SupabaseDirector(rest),
                 docs=SupabaseDocs(rest, files),
                 memory=SupabaseMemory(rest),
                 search=SupabaseSearch(rest),
                 files=files, jobs=jobs, staging=StagedCards())


def build_ports(settings: AISettings | None = None, *, sink: UsageSink | None = None,
                client: httpx.Client | None = None) -> Ports:
    """Every Supabase-backed port, for the composition root. Images are added by `adapters.images` when wanted."""
    settings = settings or get_settings()
    return _ports(Rest(settings.supabase.url, settings.supabase.service_role_key.get_secret_value(), client))


def build_context(payload: Any, *, jobs: Any, settings: AISettings | None = None,
                  client: httpx.Client | None = None, images: bool = False) -> RunContext:
    """The `RunContext` of one delivery: the real ports, the delivery's ids, and a `token_usage` writer. `jobs` is the
    function's own job store (it knows the courier hand-off); everything else is Supabase. `images` adds the painter
    (frame_render): without a key it is left out and the system reports the frame as not painted."""
    settings = settings or get_settings()
    enable_tracing(settings)  # every function builds its context here: one place turns Langfuse on (ADR 0008)
    rest = Rest(settings.supabase.url, settings.supabase.service_role_key.get_secret_value(), client)
    ctx = RunContext(production_id=payload.production_id, actor_user_id=payload.actor_user_id,
                     job_id=getattr(payload, "job_id", None),
                     usage_sink=usage_sink(rest), ports=_ports(rest, jobs), usage_detail=settings.usage_detail)
    if not images:
        return ctx
    from hiru_ai.adapters import images as painter
    from hiru_ai.core.errors import ModelUnavailable

    try:
        paint = painter.build(settings, sink=ctx.sink())
    except ModelUnavailable:
        return ctx
    return replace(ctx, ports=replace(ctx.ports, images=paint))
