"""In-memory ports for tests and for `hiru-ai run` (no network, no database).

Each fake keeps its rows in plain lists and applies writes the way the real table would (upsert by id, delete by
scene), so a test can run a tool and then read what is stored. `ports_from(fixtures)` builds the lot from one dict:

    {"production": {...}, "scenes": [...], "lines": [...], "shots": [...], "canon": [...], "documents": [...]}
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from hiru_ai.core.context import Ports
from hiru_ai.core.ports import Picture, Reference, Row
from hiru_ai.core.staging import StagedCards


def _upsert(rows: list[Row], new: list[Row]) -> None:
    index = {str(r.get("id")): n for n, r in enumerate(rows)}
    for row in new:
        n = index.get(str(row.get("id")))
        if n is None:
            index[str(row.get("id"))] = len(rows)
            rows.append(dict(row))
        else:
            rows[n] = {**rows[n], **row}


class FakeScenes:
    def __init__(self, production: Row | None = None, scenes: list[Row] | None = None, lines: list[Row] | None = None,
                 shots: list[Row] | None = None, canon: list[Row] | None = None,
                 prompts: list[Row] | None = None) -> None:
        self._production = production
        self.scene_rows = [dict(r) for r in scenes or []]
        self.line_rows = [dict(r) for r in lines or []]
        self.shot_rows = [dict(r) for r in shots or []]
        self.canon_rows = [dict(r) for r in canon or []]
        self.designs: dict[str, Row] = {}
        self.prompts: list[Row] = [dict(r) for r in prompts or []]

    def production(self, production_id: UUID) -> Row | None:
        return self._production if self._production and str(self._production.get("id")) == str(production_id) else None

    def scenes(self, production_id: UUID, scene_ids: list[str] | None) -> list[Row]:
        rows = [r for r in self.scene_rows if str(r.get("production_id")) == str(production_id)]
        return rows if scene_ids is None else [r for r in rows if str(r["id"]) in {str(i) for i in scene_ids}]

    def lines(self, scene_id: UUID | str) -> list[Row]:
        return sorted((r for r in self.line_rows if str(r.get("scene_id")) == str(scene_id)),
                      key=lambda r: int(r.get("ord") or 0))

    def shots(self, scene_id: UUID | str) -> list[Row]:
        return sorted((r for r in self.shot_rows if str(r.get("scene_id")) == str(scene_id)),
                      key=lambda r: int(r.get("number") or 0))

    def canon(self, production_id: UUID) -> list[Row]:
        return self.canon_rows

    def save_plan(self, scene_id: UUID | str, shots: list[Row], removed: list[str], lines: list[Row],
                  scene_fields: Row, removed_lines: list[str] | None = None) -> None:
        gone_lines = {str(i) for i in removed_lines or []}
        self.line_rows = [r for r in self.line_rows if str(r["id"]) not in gone_lines]
        gone = {str(i) for i in removed}
        self.shot_rows = [r for r in self.shot_rows if str(r["id"]) not in gone]
        _upsert(self.shot_rows, shots)
        _upsert(self.line_rows, lines)
        _upsert(self.scene_rows, [{"id": str(scene_id), **scene_fields}])

    def replace_shots(self, scene_id: UUID | str, shots: list[Row], lines: list[Row], scene_fields: Row) -> None:
        self.shot_rows = [r for r in self.shot_rows if str(r.get("scene_id")) != str(scene_id)]
        self.shot_rows += [dict(r) for r in shots]
        _upsert(self.line_rows, lines)
        _upsert(self.scene_rows, [{"id": str(scene_id), **scene_fields}])

    def save_design(self, shot_id: str, ir: Row, design: Row) -> None:
        self.designs[shot_id] = {"ir": ir, "design": design}
        _upsert(self.shot_rows, [{"id": shot_id, "ir": ir, "design": design}])

    def add_prompt(self, row: Row) -> None:
        self.prompts.append(dict(row))
        _upsert(self.shot_rows, [{"id": str(row["shot_id"]), "status": "prompt"}])

    def latest_prompts(self, shot_ids: list[str]) -> dict[str, Row]:
        wanted, out = {str(s) for s in shot_ids}, {}
        for row in sorted(self.prompts, key=lambda r: int(r.get("version") or 0)):
            if str(row["shot_id"]) in wanted:
                out[str(row["shot_id"])] = dict(row)
        return out


class FakeCanon:
    def __init__(self, entities: list[Row] | None = None, looks: list[Row] | None = None) -> None:
        self.entity_rows = [dict(r) for r in entities or []]
        self.versions: list[Row] = []
        self.look_rows = [dict(r) for r in looks or []]

    def entities(self, production_id: UUID) -> list[Row]:
        """Each entity with its current version joined in as `current`, as the real query returns it."""
        by_id = {str(v["id"]): v for v in self.versions}
        return [{**e, "current": by_id.get(str(e.get("current_version_id")), e.get("current"))}
                for e in self.entity_rows]

    def create_entity(self, entity: Row, version: Row) -> None:
        self.entity_rows.append({**entity, "current_version_id": version["id"]})
        self.versions.append(dict(version))

    def add_version(self, entity_id: str, version: Row, fields: Row) -> None:
        self.versions.append(dict(version))
        self.update_entity(entity_id, {**fields, "current_version_id": version["id"]})

    def update_entity(self, entity_id: str, fields: Row) -> None:
        _upsert(self.entity_rows, [{"id": entity_id, **fields}])

    def looks(self, production_id: UUID) -> list[Row]:
        return [dict(r) for r in self.look_rows]


class FakeStructure:
    def __init__(self, episodes: list[Row] | None = None, scenes: list[Row] | None = None,
                 questions: list[Row] | None = None) -> None:
        self.question_rows: dict[str, Row] = {str(q.get("id", n)): dict(q) for n, q in enumerate(questions or [])}
        self.look_rows: list[Row] = []
        self.episode_rows = [dict(r) for r in episodes or []]
        self.scene_rows = [dict(r) for r in scenes or []]
        self.line_rows: list[Row] = []

    def episodes(self, production_id: UUID) -> list[Row]:
        return self.episode_rows

    def scene_headers(self, production_id: UUID) -> list[Row]:
        return self.scene_rows

    def upsert_episodes(self, rows: list[Row]) -> None:
        _upsert(self.episode_rows, rows)

    def write_scene(self, scene: Row, lines: list[Row]) -> None:
        _upsert(self.scene_rows, [scene])
        self.line_rows = [r for r in self.line_rows if str(r.get("scene_id")) != str(scene["id"])]
        self.line_rows += [dict(r) for r in lines]

    def delete_scenes(self, scene_ids: list[str]) -> None:
        gone = {str(i) for i in scene_ids}
        self.scene_rows = [r for r in self.scene_rows if str(r["id"]) not in gone]

    def upsert_questions(self, rows: list[Row]) -> None:
        for row in rows:
            self.question_rows[str(row["id"])] = dict(row)

    def answers(self, job_id: UUID) -> list[Row]:
        return [{"key": q["key"], "status": q["status"], "answer": q.get("answer")}
                for q in self.question_rows.values() if str(q.get("job_id")) == str(job_id)]

    def earlier_answers(self, production_id: UUID) -> list[Row]:
        return [{"key": q["key"], "answer": q.get("answer")} for q in self.question_rows.values()
                if q.get("status") == "answered"]

    def entities_with_looks(self, production_id: UUID) -> set[str]:
        return {str(r["entity_id"]) for r in self.look_rows}

    def create_looks(self, rows: list[Row]) -> None:
        self.look_rows += [dict(r) for r in rows]

    def open_questions(self, production_id: UUID) -> list[Row]:
        return [{"scope": q.get("scope", ""), "title": q.get("title", ""), "body": q.get("body", ""),
                 "key": q.get("key", "")}
                for q in self.question_rows.values()
                if q.get("status", "open") == "open"
                   and str(q.get("production_id", production_id)) == str(production_id)]


class FakeSplit:
    """`SplitStore` in memory."""

    def __init__(self, episodes: list[Row] | None = None, scenes: list[Row] | None = None,
                 characters: list[Row] | None = None, locations: list[Row] | None = None) -> None:
        self.episode_rows = [dict(r) for r in episodes or []]
        self.scene_rows = scenes if scenes is not None else []
        self.character_rows = characters or []
        self.location_rows = locations or []

    def episodes(self, production_id: UUID) -> list[Row]:
        return self.episode_rows

    def neighbours(self, production_id: UUID) -> list[Row]:
        return [{k: s.get(k) for k in ("id", "episode_id", "number", "heading", "title")} for s in self.scene_rows]

    def characters(self, production_id: UUID) -> list[Row]:
        return self.character_rows

    def locations(self, production_id: UUID) -> list[Row]:
        return self.location_rows

    def scene_status(self, production_id: UUID) -> list[Row]:
        return [{"episode_id": s["episode_id"], "status": s["status"]} for s in self.scene_rows]

    def set_episode_status(self, episode_id: str, status: str) -> None:
        _upsert(self.episode_rows, [{"id": episode_id, "status": status}])


class FakeProducer:
    """`ProducerStore` in memory."""

    def __init__(self, scenes: list[Row] | None = None, shots: list[Row] | None = None,
                 prompts: list[Row] | None = None, frames: dict[str, Row] | None = None,
                 persona: Row | None = None) -> None:
        self.scene_rows = scenes if scenes is not None else []
        self.shot_rows = shots if shots is not None else []
        self.prompt_rows = prompts if prompts is not None else []
        self.accepted = frames if frames is not None else {}
        self.persona = persona
        self.intents: dict[str, Row] = {}
        self.coverage: dict[str, Row] = {}
        self.audits: list[Row] = []

    def neighbours(self, scene: Row) -> tuple[Row | None, Row | None]:
        number = int(scene.get("number") or 0)
        same = [s for s in self.scene_rows if str(s.get("episode_id")) == str(scene.get("episode_id"))]
        by_number = {int(s["number"]): s for s in same}
        return by_number.get(number - 1), by_number.get(number + 1)

    def shot_scenes(self, production_id: UUID, shot_ids: list[str]) -> list[str]:
        wanted = {str(i) for i in shot_ids}
        return list(dict.fromkeys(str(s["scene_id"]) for s in self.shot_rows if str(s["id"]) in wanted))

    def lead_persona(self, production_id: UUID) -> Row | None:
        return self.persona

    def accepted_frames(self, shot_ids: list[str]) -> dict[str, Row]:
        return {k: v for k, v in self.accepted.items() if k in shot_ids}

    def last_prompt_version(self, shot_id: str) -> int:
        return max((int(p["version"]) for p in self.prompt_rows if str(p["shot_id"]) == str(shot_id)), default=0)

    def save_intent(self, shot_id: str, intent: Row) -> None:
        self.intents[shot_id] = intent
        _upsert(self.shot_rows, [{"id": shot_id, "intent": intent}])

    def save_coverage(self, scene_id: str, coverage: Row) -> None:
        self.coverage[scene_id] = coverage
        _upsert(self.scene_rows, [{"id": scene_id, "coverage": coverage}])

    def audit(self, row: Row) -> None:
        self.audits.append(row)


class FakeDirector:
    """`DirectorStore` in memory (thread, board, pending action, memory)."""

    def __init__(self, scene: Row | None = None) -> None:
        self.scene_row = scene
        self.board_rows: list[Row] = []
        self.history: list[Row] = []
        self.message_rows: list[Row] = []
        self.pending_rows: list[Row] = []
        self.memory_rows: list[Row] = []
        self.audits: list[Row] = []

    def scene(self, production_id: UUID, scene_id: UUID) -> Row | None:
        row = self.scene_row
        ok = row and str(row["production_id"]) == str(production_id) and str(row["id"]) == str(scene_id)
        return row if ok else None

    def board(self, production_id: UUID) -> list[Row]:
        return self.board_rows

    def default_persona(self) -> Row | None:
        return None

    def messages(self, thread_id: UUID, limit: int = 12) -> list[Row]:
        return self.history[-limit:]

    def message(self, message_id: UUID | str) -> Row | None:
        return next((m for m in [*self.history, *self.message_rows] if str(m.get("id")) == str(message_id)), None)

    def open_pending(self, thread_id: UUID | str) -> Row | None:
        return next((p for p in self.pending_rows if p["status"] == "open" and str(p["thread_id"]) == str(thread_id)),
                    None)

    def add_pending(self, row: Row) -> None:
        self.pending_rows.append(dict(row))

    def close_pending(self, thread_id: UUID | str, status: str) -> None:
        for p in self.pending_rows:
            if p["status"] == "open" and str(p["thread_id"]) == str(thread_id):
                p["status"] = status

    def set_blocks(self, message_id: UUID | str, blocks: list[Row]) -> None:
        if (m := self.message(message_id)) is not None:
            m["blocks"] = blocks

    def memory(self, production_id: UUID, limit: int = 20) -> list[Row]:
        return [{"kind": m["kind"], "text": m["text"]} for m in self.memory_rows][:limit]

    def open_questions(self, production_id: UUID) -> list[Row]:
        return []

    def ready_documents(self, production_id: UUID) -> list[Row]:
        return []

    def search(self, *, query: str, embedding: list[float] | None, production_id: UUID, document_ids: list[str],
               k: int = 6) -> list[Row]:
        return []

    def add_message(self, row: Row) -> None:
        self.message_rows.append(row)

    def add_memory(self, item: Row, embedding: list[float] | None, model: str) -> None:
        self.memory_rows.append({**item, "embedding": embedding})

    def audit(self, row: Row) -> None:
        self.audits.append(row)


class FakeRevisions:
    """`RevisionStore` in memory. `missing=True` is a database without the table: every call raises."""

    def __init__(self, *, missing: bool = False) -> None:
        self.rows: list[Row] = []
        self.missing = missing

    def _check(self) -> None:
        if self.missing:
            raise RuntimeError("scene_plan_revisions does not exist")

    def revisions(self, scene_id: UUID | str) -> list[Row]:
        self._check()
        return sorted((dict(r) for r in self.rows if str(r["scene_id"]) == str(scene_id)),
                      key=lambda r: int(r["revision"]))

    def add_revision(self, row: Row) -> None:
        self._check()
        self.rows.append(dict(row))

    def drop_revisions(self, scene_id: UUID | str, numbers: list[int]) -> None:
        self._check()
        gone = set(numbers)
        self.rows = [r for r in self.rows if not (str(r["scene_id"]) == str(scene_id) and int(r["revision"]) in gone)]


class FakeFrames:
    """`FrameStore` in memory: the frames a job paints, the looks and the shots they read."""

    def __init__(self, frames: list[Row] | None = None, shots: list[Row] | None = None, scene: Row | None = None,
                 looks: list[Row] | None = None, scene_looks: list[Row] | None = None, episode: int = 1,
                 canon: list[Row] | None = None) -> None:
        self.canon_rows = [dict(r) for r in canon or []]
        self.frame_rows: dict[str, Row] = {str(f["id"]): dict(f) for f in frames or []}
        self.shot_rows = {str(s["id"]): s for s in shots or []}
        self.scene_row = scene
        self.look_rows: dict[str, Row] = {str(r["id"]): dict(r) for r in looks or []}
        self.scene_look_rows = scene_looks or []
        self.episode = episode
        self.asset_writes: list[tuple[str, list[Any]]] = []
        self.look_writes: list[tuple[str, list[Any]]] = []
        self.audits: list[Row] = []

    def frames(self, production_id: UUID, frame_ids: list[str]) -> list[Row]:
        return [dict(self.frame_rows[f]) for f in frame_ids if f in self.frame_rows]

    def shot(self, shot_id: str) -> Row | None:
        return self.shot_rows.get(shot_id)

    def scene(self, scene_id: str) -> Row | None:
        return self.scene_row

    def look(self, look_id: str) -> Row | None:
        return self.look_rows.get(look_id)

    def looks(self, production_id: UUID) -> list[Row]:
        return list(self.look_rows.values())

    def scene_looks(self, scene_id: str) -> list[Row]:
        return self.scene_look_rows

    def episode_number(self, episode_id: str) -> int | None:
        return self.episode

    def claim_frame(self, frame_id: str) -> bool:
        row = self.frame_rows[frame_id]
        if row["status"] != "queued":
            return False
        row["status"] = "running"
        return True

    def finish_frame(self, frame_id: str, fields: Row) -> None:
        self.frame_rows[frame_id].update(fields)

    def add_reference_asset(self, version_id: str, assets: list[Any]) -> None:
        self.asset_writes.append((version_id, assets))

    def finish_look_sheet(self, look_id: str, assets: list[Any]) -> None:
        self.look_writes.append((look_id, assets))
        self.look_rows[look_id].update(sheet_assets=assets, status="draft")

    def audit(self, row: Row) -> None:
        self.audits.append(row)

    def frame_status(self, production_id: UUID, shot_ids: list[str] | None = None,
                     codes: list[str] | None = None) -> Row:
        wanted = {str(s) for s in shot_ids or []}
        frames = [{"id": str(r["id"]), "shot_id": str(r["shot_id"]), "status": r.get("status", ""),
                   "accepted": bool(r.get("accepted_at")), "pins": r.get("pins") or {}, "error": r.get("error"),
                   "created_at": r.get("created_at")}
                  for r in self.frame_rows.values()
                  if str(r.get("shot_id")) in wanted and r.get("stage") != "draft"
                     and str(r.get("production_id", production_id)) == str(production_id)]
        sheets = []
        for code in codes or []:
            entity = next((e for e in self.canon_rows if str(e.get("code")) == code), None)
            if entity is None:
                continue
            own = [r for r in self.look_rows.values() if str(r.get("entity_id")) == str(entity["id"])]
            sheets.append({"code": code, "name": entity.get("name", ""), "kind": entity.get("kind", ""),
                           "sheets": len((entity.get("current") or {}).get("reference_assets") or []),
                           "looks": [{"name": r.get("name", ""), "status": r.get("status", ""),
                                      "sheets": len(r.get("sheet_assets") or []), "ranges": r.get("ranges") or []}
                                     for r in own]})
        return {"frames": frames, "sheets": sheets}


FakeStaging = StagedCards  # the real thing is just a list; the fake keeps the test-side name


class FakeDocs:
    def __init__(self, documents: list[Row] | None = None, texts: dict[str, str] | None = None) -> None:
        self.document_rows = [dict(r) for r in documents or []]
        self.texts = dict(texts or {})

    def documents(self, production_id: UUID) -> list[Row]:
        return [r for r in self.document_rows if str(r.get("production_id", production_id)) == str(production_id)]

    def text(self, path: str) -> str:
        return self.texts[path]

    def get_document(self, document_id: UUID) -> Row | None:
        return next((r for r in self.document_rows if str(r.get("id")) == str(document_id)), None)

    def update_document(self, document_id: UUID, fields: Row) -> None:
        row = self.get_document(document_id)
        assert row is not None, "no such document"
        row.update(fields)

    def existing_embeddings(self, document_id: UUID) -> dict[str, tuple[list[float], str]]:
        return {r["content_hash"]: (r["embedding"], r["embedding_model"]) for r in getattr(self, "chunk_rows", [])
                if str(r["document_id"]) == str(document_id) and r.get("embedding") is not None}

    def replace_chunks(self, document_id: UUID, rows: list[Row]) -> None:
        kept = [r for r in getattr(self, "chunk_rows", []) if str(r["document_id"]) != str(document_id)]
        self.chunk_rows = [*kept, *[dict(r) for r in rows]]


class FakeMemory:
    """A `MemoryStore` that keeps its entries in a list, applying `replace_from` the way the real table does."""

    def __init__(self, entries: list[Row] | None = None) -> None:
        self.rows = [dict(r) for r in entries or []]
        self.broken: Exception | None = None  # tests: the table is missing (the migration is not applied yet)
        self.reads = 0

    def entries(self, production_id: UUID) -> list[Row]:
        self.reads += 1
        if self.broken is not None:
            raise self.broken
        return [dict(r) for r in self.rows if str(r.get("production_id", production_id)) == str(production_id)]

    def replace_from(self, production_id: UUID, document_id: UUID, entries: list[Row]) -> None:
        from hiru_ai.core import memory

        if self.broken is not None:
            raise self.broken
        mine = [r for r in self.rows if str(r.get("document_id")) == str(document_id)]
        kept = [r for r in mine if not memory.is_reader_draft(r)]
        self.rows = [r for r in self.rows if str(r.get("document_id")) != str(document_id) or r in kept]
        self.rows += [{"id": f"m{len(self.rows) + n}", "production_id": str(production_id),
                       "document_id": str(document_id), "status": "draft", "source": "reader", **e}
                      for n, e in enumerate(memory.fresh(kept, entries))]

    def upsert(self, row: Row) -> None:
        if self.broken is not None:
            raise self.broken
        _upsert(self.rows, [row if "id" in row else {**row, "id": f"m{len(self.rows)}"}])


class FakeSearch:
    """Returns the rows it was given, and remembers how it was asked (so a test can check the scope)."""

    def __init__(self, chunks: list[Row] | None = None, techniques: list[Row] | None = None) -> None:
        self.chunk_rows = [dict(r) for r in chunks or []]
        self.technique_rows = [dict(r) for r in techniques or []]
        self.asked: list[dict[str, Any]] = []

    def chunks(self, *, query: str, embedding: list[float] | None, production_id: UUID, corpora: list[str],
               document_ids: list[str] | None, k: int) -> list[Row]:
        self.asked.append({"query": query, "embedding": embedding, "production_id": str(production_id),
                           "corpora": corpora, "document_ids": document_ids, "k": k})
        return self.chunk_rows[:k]

    def techniques(self, query: str, embedding: list[float] | None, k: int = 4) -> list[Row]:
        self.asked.append({"technique_query": query, "embedding": embedding, "k": k})
        return self.technique_rows[:k]

    def memory(self, query: str, embedding: list[float] | None, production_id: UUID, k: int = 6) -> list[Row]:
        self.asked.append({"memory_query": query, "embedding": embedding, "production_id": str(production_id), "k": k})
        return [r for r in self.chunk_rows if r.get("corpus") == "memory"][:k]


class FakeKnowledge:
    """A `KnowledgeStore` that keeps what an ingest wrote, so a test can read it back."""

    def __init__(self, chunks: list[Row] | None = None, techniques: list[Row] | None = None) -> None:
        self.chunk_rows = [dict(r) for r in chunks or []]
        self.technique_rows = [dict(r) for r in techniques or []]

    def embeddings(self, corpus: str, source_prefix: str) -> dict[str, Any]:
        return {r["content_hash"]: r["embedding"] for r in self.chunk_rows
                if r.get("corpus") == corpus and str(r.get("source", "")).startswith(source_prefix)
                and r.get("embedding") is not None}

    def replace_chunks(self, corpus: str, source_prefix: str, rows: list[Row]) -> None:
        self.chunk_rows = [r for r in self.chunk_rows
                           if not (r.get("corpus") == corpus and str(r.get("source", "")).startswith(source_prefix))]
        self.chunk_rows += [dict(r) for r in rows]

    def replace_techniques(self, rows: list[Row]) -> None:
        self.technique_rows = [dict(r) for r in rows]


class FakeFiles:
    def __init__(self, objects: dict[tuple[str, str], bytes] | None = None) -> None:
        self.objects = dict(objects or {})

    def download(self, bucket: str, path: str) -> bytes:
        return self.objects[(bucket, path)]

    def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None:
        self.objects[(bucket, path)] = data


class FakeImages:
    """Paints a fixed picture, or raises what it was told to."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, str, list[Reference]]] = []
        self.drafts: list[bool] = []  # per call: was it painted as a draft

    def __call__(self, prompt: str, aspect: str, references: list[Reference], *, draft: bool = False) -> Picture:
        self.calls.append((prompt, aspect, list(references)))
        self.drafts.append(draft)
        if self.error is not None:
            raise self.error
        return Picture(data=b"\x89PNG-fake", mime="image/png", input_tokens=120, output_tokens=1056)


class FakeJobs:
    """The job contract in memory: a finished job is skipped, a stale hop is skipped, events and stages are kept."""

    def __init__(self, status: str = "pending", cursor: int = 0) -> None:
        self.status, self.cursor = status, cursor
        self.fields: dict[str, Any] = {}
        self.events: list[dict[str, Any]] = []
        self.advanced: list[dict[str, Any]] = []
        self.missing = False

    def check(self, payload: Any) -> str | None:
        if self.missing:
            return "missing job"
        if self.status in ("done", "failed", "cancelled"):
            return self.status
        if self.cursor != payload.cursor:
            return "stale hop"
        if self.status == "waiting_input" and not payload.resuming:
            return "waiting for answers"
        return None

    def set(self, job_id: UUID, status: Any, **fields: Any) -> None:
        self.status = status.value
        self.fields.update(fields)
        self.events.append({"type": "status", "status": status.value})

    def event(self, job_id: UUID, type_: Any, payload: dict[str, Any], agent: str | None = None) -> None:
        self.events.append({"type": type_.value, "agent": agent, **payload})

    def stage(self, job_id: UUID, stage: str, state: str, text: str = "") -> None:
        self.events.append({"type": "stage", "stage": stage, "state": state, "text": text})

    def finish(self, payload: Any, result: dict[str, Any], next_state: dict[str, Any] | None = None, *,
               again: bool = False) -> None:
        if payload.is_last_hop and not again:
            self.set(payload.job_id, type("S", (), {"value": "done"})(), result=result)
        else:
            self.advanced.append({"cursor": payload.cursor, "again": again,
                                  "state": {**(next_state or {}), "previous": result}})

    def texts(self, type_: str | None = None) -> list[str]:
        return [str(e.get("text", "")) for e in self.events if type_ is None or e["type"] == type_]


def ports_from(fixtures: dict[str, Any]) -> Ports:
    """Every fake, filled from one fixtures dict (see the module doc). Missing keys give empty stores."""
    scenes = FakeScenes(fixtures.get("production"), fixtures.get("scenes"), fixtures.get("lines"),
                        fixtures.get("shots"), fixtures.get("canon"), fixtures.get("prompts"))
    return Ports(scenes=scenes, canon=FakeCanon(fixtures.get("canon"), fixtures.get("looks")),
                 structure=FakeStructure(fixtures.get("episodes"), fixtures.get("scene_headers"),
                                       fixtures.get("questions")),
                 docs=FakeDocs(fixtures.get("documents"), fixtures.get("texts")),
                 memory=FakeMemory(fixtures.get("memory")),
                 search=FakeSearch(fixtures.get("chunks"), fixtures.get("techniques")),
                 split=FakeSplit(fixtures.get("episodes"), fixtures.get("scenes")),
                 frames=FakeFrames(fixtures.get("frames"), fixtures.get("shots"), None, fixtures.get("looks"),
                                   canon=fixtures.get("canon")),
                 files=FakeFiles(), images=FakeImages(), staging=FakeStaging())
