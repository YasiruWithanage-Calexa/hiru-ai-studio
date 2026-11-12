"""Ports: the shapes of the outside world a part may use. Parts import these, never an adapter.

A port is a `Protocol`, so a real adapter (Supabase REST, storage, the image API) and a test fake satisfy it
without sharing a base class. The methods are the ones today's stores and handlers already have
(`runtime/store.py`, `runtime/jobs.py`, `frame_render`'s painter); Phase 2 widened them to what the tools need.
Every adapter lives in `hiru_ai/adapters/`; the in-memory fakes in `core/fakes.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

Row = dict[str, Any]


class SceneStore(Protocol):
    """A production's scenes, lines and shots: the reads, and the two ways a plan is saved."""

    def production(self, production_id: UUID) -> Row | None: ...
    def scenes(self, production_id: UUID, scene_ids: list[str] | None) -> list[Row]: ...
    def lines(self, scene_id: UUID | str) -> list[Row]: ...
    def shots(self, scene_id: UUID | str) -> list[Row]: ...
    def canon(self, production_id: UUID) -> list[Row]: ...

    def save_plan(self, scene_id: UUID | str, shots: list[Row], removed: list[str], lines: list[Row],
                  scene_fields: Row, removed_lines: list[str] | None = None) -> None:
        """An edited plan (the director). Shots keep their ids, so frames and prompts stay attached."""

    def replace_shots(self, scene_id: UUID | str, shots: list[Row], lines: list[Row], scene_fields: Row) -> None:
        """A fresh plan (the splitter): the scene's shots go, the new ones are written. Safe to repeat."""

    def save_design(self, shot_id: str, ir: Row, design: Row) -> None: ...
    def add_prompt(self, row: Row) -> None: ...

    def latest_prompts(self, shot_ids: list[str]) -> dict[str, Row]:
        """shot id → the newest prompt version of that shot (`version, sections, prose, checks, pins, frame_id`)."""


class CanonStore(Protocol):
    """Canon entities and their versions."""

    def entities(self, production_id: UUID) -> list[Row]: ...
    def create_entity(self, entity: Row, version: Row) -> None: ...
    def add_version(self, entity_id: str, version: Row, fields: Row) -> None: ...
    def update_entity(self, entity_id: str, fields: Row) -> None: ...

    def looks(self, production_id: UUID) -> list[Row]:
        """Every look of the production's characters (`canon_looks`): name, episode ranges, outfit, hair, makeup,
        accessories, status. The sheets' storage paths are for the painter; a reader asks `FrameStore.frame_status`."""

    def refine_apply(self, production_id: UUID, payload: Row) -> Row:
        """One canon refine's answer written in one transaction (`canon_refine_apply`, schema v23, plan/2026-11-12c
        §3.4): new versions switch only where the card read is still current, came from extract, inferred or refine and
        is not locked (else a proposal); draft looks never replace a person's; a person's scene look wins. Returns the
        counts: switched, proposed, skipped_changed, unchanged, looks, scene_looks."""


class StructureStore(Protocol):
    """Episodes and scenes as the structure build writes them, the questions it asks, and the looks it drafts."""

    def episodes(self, production_id: UUID) -> list[Row]: ...
    def scene_headers(self, production_id: UUID) -> list[Row]: ...
    def upsert_episodes(self, rows: list[Row]) -> None: ...
    def write_scene(self, scene: Row, lines: list[Row]) -> None: ...
    def delete_scenes(self, scene_ids: list[str]) -> None: ...

    def upsert_questions(self, rows: list[Row]) -> None: ...
    def answers(self, job_id: UUID) -> list[Row]:
        """A job's questions as `{key, status, answer}`."""

    def earlier_answers(self, production_id: UUID) -> list[Row]:
        """Questions people answered in earlier builds as `{key, answer}`, oldest first (the latest wins)."""

    def entities_with_looks(self, production_id: UUID) -> set[str]: ...
    def create_looks(self, rows: list[Row]) -> None: ...

    def open_questions(self, production_id: UUID) -> list[Row]:
        """The questions still waiting for a person, as `{scope, title, body, key}`, oldest first."""


class DocStore(Protocol):
    """Uploaded documents, their extracted text, and the passages indexed from them."""

    def documents(self, production_id: UUID) -> list[Row]: ...
    def text(self, path: str) -> str: ...
    def get_document(self, document_id: UUID) -> Row | None: ...
    def update_document(self, document_id: UUID, fields: Row) -> None: ...
    def existing_embeddings(self, document_id: UUID) -> dict[str, tuple[list[float], str]]:
        """content_hash → (embedding, model) of the document's current passages, to reuse (embedding costs money)."""

    def replace_chunks(self, document_id: UUID, rows: list[Row]) -> None:
        """The document's passages become exactly `rows`: a re-run replaces, never appends."""


class MemoryStore(Protocol):
    """The production's memory: what its documents (and its people) say about how to make the drama, one entry per row
    (`production_memory`, plan/2026-11-05d). Not the director's `memory_items` (decisions, notes) and not the search
    corpus `memory`."""

    def entries(self, production_id: UUID) -> list[Row]:
        """Every entry of the production, any status, oldest first: `id, document_id, topic, applies_to, says, quote,
        strength, status, source`."""

    def replace_from(self, production_id: UUID, document_id: UUID, entries: list[Row]) -> None:
        """A document's reader drafts become exactly `entries` (`topic, applies_to, says, quote, strength`). An entry a
        person approved, rejected or edited is kept, and a new entry that says what one of those already says is not
        added again (a rejected direction does not come back as a draft). Safe to repeat."""

    def upsert(self, row: Row) -> None:
        """A person's entry, new (no `id`) or changed."""


class BreakdownStore(Protocol):
    """The two memories of a production and each scene's packet (plan/2026-11-11 §5, schema v21). The source memory is
    written once per document and never edited; the breakdown memory is one JSON document per production (D7); a scene's
    packet is assembled from it by code and kept beside the scene for the planners and the read-only view."""

    def sources(self, production_id: UUID) -> list[Row]:
        """Each document's source memory, in upload order: `document_id, filename, body`."""

    def save_source(self, production_id: UUID, document_id: str, filename: str, body: Row) -> None:
        """Written once (decision 7): a document that already has one keeps it."""

    def memory(self, production_id: UUID) -> Row | None:
        """`body, version` or None (no breakdown yet)."""

    def save_memory(self, production_id: UUID, body: Row, version: int) -> None: ...

    def packet(self, scene_id: str) -> Row | None:
        """`scene_id, scene_key, packet, waits, script_version, memory_version` or None."""

    def save_packets(self, production_id: UUID, rows: list[Row]) -> None:
        """Upsert by scene id."""

    def set_staging(self, scene_id: str, staging: Row) -> None:
        """`scenes.staging`, filled from the breakdown memory's stager map (D1)."""


class Search(Protocol):
    """Retrieval over `chunks`. The scope (production, corpora, documents) is the caller's, from trusted data."""

    def chunks(self, *, query: str, embedding: list[float] | None, production_id: UUID, corpora: list[str],
               document_ids: list[str] | None, k: int) -> list[Row]: ...
    def techniques(self, query: str, embedding: list[float] | None, k: int = 4) -> list[Row]: ...

    def memory(self, query: str, embedding: list[float] | None, production_id: UUID, k: int = 6) -> list[Row]:
        """The production's remembered decisions only (corpus `memory`), best first: the same rows and total order as
        `chunks`, with `source` = `memory:<memory_items.id>`."""


class SplitStore(Protocol):
    """What the shot splitter reads around a scene and the one status it writes (script_split); the scenes, lines and
    the shots themselves go through `SceneStore`."""

    def episodes(self, production_id: UUID) -> list[Row]:
        """`id, number, title, synopsis, status` of each episode."""

    def neighbours(self, production_id: UUID) -> list[Row]:
        """Every scene's `id, episode_id, number, heading, title`, for the scenes either side of the one being read."""

    def characters(self, production_id: UUID) -> list[Row]: ...
    def locations(self, production_id: UUID) -> list[Row]: ...
    def scene_status(self, production_id: UUID) -> list[Row]: ...
    def set_episode_status(self, episode_id: str, status: str) -> None: ...


class ProducerStore(Protocol):
    """What the shot producer reads around a scene and the intents it saves (shot_producer); the scenes, lines, canon,
    designs and prompt versions go through `SceneStore`, the technique lookup through `Search`."""

    def neighbours(self, scene: Row) -> tuple[Row | None, Row | None]:
        """The scenes either side of this one in its episode, for the story context."""

    def shot_scenes(self, production_id: UUID, shot_ids: list[str]) -> list[str]: ...
    def lead_persona(self, production_id: UUID) -> Row | None: ...
    def accepted_frames(self, shot_ids: list[str]) -> dict[str, Row]: ...
    def last_prompt_version(self, shot_id: str) -> int: ...
    def save_intent(self, shot_id: str, intent: Row) -> None: ...
    def save_coverage(self, scene_id: str, coverage: Row) -> None: ...
    def audit(self, row: Row) -> None: ...


class DirectorStore(Protocol):
    """What a director turn reads and writes beside the scene (director_chat): the board, the thread, the pending
    action, the production's memory. The scene's lines, shots and canon and the saved plan go through `SceneStore`."""

    def scene(self, production_id: UUID, scene_id: UUID) -> Row | None: ...
    def board(self, production_id: UUID) -> list[Row]: ...
    def default_persona(self) -> Row | None: ...
    def messages(self, thread_id: UUID, limit: int = 12) -> list[Row]: ...
    def message(self, message_id: UUID | str) -> Row | None: ...
    def open_pending(self, thread_id: UUID | str) -> Row | None: ...
    def add_pending(self, row: Row) -> None: ...
    def close_pending(self, thread_id: UUID | str, status: str) -> None: ...
    def set_blocks(self, message_id: UUID | str, blocks: list[Row]) -> None: ...
    def memory(self, production_id: UUID, limit: int = 20) -> list[Row]: ...
    def open_questions(self, production_id: UUID) -> list[Row]: ...
    def ready_documents(self, production_id: UUID) -> list[Row]: ...
    def search(self, *, query: str, embedding: list[float] | None, production_id: UUID, document_ids: list[str],
               k: int = 6) -> list[Row]: ...
    def add_message(self, row: Row) -> None: ...
    def add_memory(self, item: Row, embedding: list[float] | None, model: str) -> None: ...
    def audit(self, row: Row) -> None: ...


class ChatStore(Protocol):
    """A chat thread a production assistant reads and answers in (Sable, plan/2026-11-08 §4.5, §4.8): the thread with
    its stored summary, its messages, the reply. `chat_threads.summary` and `.summarised` (how many of the oldest
    messages the summary covers) and `chat_turn_meta` (a reply's `meta`) are schema v18."""

    def thread(self, thread_id: UUID | str) -> Row | None: ...
    def messages(self, thread_id: UUID | str, limit: int = 200) -> list[Row]:
        """The thread's messages, oldest first (at most `limit`, the newest kept)."""

    def add_message(self, row: Row) -> None: ...
    def set_summary(self, thread_id: UUID | str, summary: str, summarised: int) -> None: ...


class RevisionStore(Protocol):
    """A scene's plan revisions, behind undo and redo in the director chat (plan/2026-11-06e §4.7,
    `scene_plan_revisions`). A store whose database has no such table raises; the caller then runs without undo."""

    def revisions(self, scene_id: UUID | str) -> list[Row]:
        """Every kept revision of the scene, oldest first."""

    def add_revision(self, row: Row) -> None: ...
    def drop_revisions(self, scene_id: UUID | str, numbers: list[int]) -> None: ...


class FrameStore(Protocol):
    """The frames a job paints, and what it reads about their shots, canon and looks (frame_render)."""

    def frames(self, production_id: UUID, frame_ids: list[str]) -> list[Row]: ...
    def shot(self, shot_id: str) -> Row | None: ...
    def scene(self, scene_id: str) -> Row | None: ...
    def look(self, look_id: str) -> Row | None: ...
    def looks(self, production_id: UUID) -> list[Row]: ...
    def scene_looks(self, scene_id: str) -> list[Row]: ...
    def episode_number(self, episode_id: str) -> int | None: ...
    def accepted_finals(self, shot_ids: list[str]) -> dict[str, Row]:
        """shot id → its accepted FINAL frame (`id, shot_id, storage_path`), for the shots that have one: the
        same-setup frame a later shot of that setup is painted against (plan/2026-11-11b)."""

    def claim_frame(self, frame_id: str) -> bool:
        """queued -> running, or False when another delivery already has it: a re-delivered task must not pay for
        the same picture twice."""

    def finish_frame(self, frame_id: str, fields: Row) -> None: ...
    def add_reference_asset(self, version_id: str, assets: list[Any]) -> None: ...
    def finish_look_sheet(self, look_id: str, assets: list[Any]) -> None: ...
    def audit(self, row: Row) -> None: ...

    def frame_status(self, production_id: UUID, shot_ids: list[str] | None = None,
                     codes: list[str] | None = None) -> Row:
        """What exists, never where it is stored: `{"frames": [...], "sheets": [...]}`. `frames` are the first frames of
        the given shots (`id, shot_id, status, accepted, pins, error, created_at`); `sheets` are the reference sheets of
        the given canon codes (`code, name, kind, sheets, looks: [{name, status, sheets, ranges}]`, counts of files)."""


class KnowledgeStore(Protocol):
    """Where `hiru-ai ingest` writes a knowledge base. Not a run port: no agent or tool changes a knowledge base,
    only the ingest command (a composition root) does.

    A chunk row is replaced by the SOURCE PREFIX its knowledge base owns, so several bases can share the `craft`
    corpus (craft, guides, rules) without deleting each other's rows.
    """

    def embeddings(self, corpus: str, source_prefix: str) -> dict[str, Any]:
        """content_hash → the embedding already stored for that exact text and model (re-embedding costs money)."""

    def replace_chunks(self, corpus: str, source_prefix: str, rows: list[Row]) -> None: ...
    def replace_techniques(self, rows: list[Row]) -> None: ...


class Staging(Protocol):
    """Where a `stage` tool leaves a card for a person to accept. The run's owner (the director turn) reads the cards
    back with `staged()` and shows them; nothing here changes the plan, the script or the canon, and a tool never
    reaches the database through it (plan/2026-11-04 §4.3)."""

    def add(self, card: Row) -> str:
        """Keep the card; -> its id."""

    def staged(self) -> list[Row]:
        """The cards added so far, oldest first."""


class Files(Protocol):
    """Binary storage. Never hands a storage-provider URL to a client (CLAUDE.md "Files")."""

    def download(self, bucket: str, path: str) -> bytes: ...
    def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None: ...


@dataclass(frozen=True)
class Reference:
    label: str  # what the prompt calls it ("Kamala's character sheet")
    data: bytes
    mime: str = "image/png"


@dataclass(frozen=True)
class Picture:
    data: bytes
    mime: str
    input_tokens: int
    output_tokens: int


class ImageRefused(Exception):
    """The image model declined to make the picture. Terminal and reportable, never retried."""


class ImageFailed(Exception):
    """The provider failed in a way a retry inside the call could not fix."""


class ImageGen(Protocol):
    """Paint one picture from a prompt and labelled reference images, sent in the order the prompt numbers them.
    `draft` paints it at the draft quality (low): the cheap try a person settles the picture with."""

    def __call__(self, prompt: str, aspect: str, references: list[Reference], *, draft: bool = False) -> Picture: ...


class Jobs(Protocol):
    """The job contract every function follows: skip a finished or stale delivery, report progress, finish."""

    def check(self, payload: Any) -> str | None: ...
    def set(self, job_id: UUID, status: Any, **fields: Any) -> None: ...
    def event(self, job_id: UUID, type_: Any, payload: dict[str, Any], agent: str | None = None) -> None: ...
    def stage(self, job_id: UUID, stage: str, state: str, text: str = "") -> None: ...
    def finish(self, payload: Any, result: dict[str, Any], next_state: dict[str, Any] | None = None, *,
               again: bool = False) -> None: ...
