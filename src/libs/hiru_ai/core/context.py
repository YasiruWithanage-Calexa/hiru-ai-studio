"""RunContext: everything a run needs from outside, passed in, never imported.

It is the LangGraph `context_schema`: nodes and tools read the scope, the actor, the job and the ports from it.
The composition root (a function handler, the API, the CLI, a test) builds it with real adapters or fakes.

Search and write scope (production, corpora, documents, roles) comes from the trusted payload through this
object, never from anything a model said (CLAUDE.md "AI and RAG").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from hiru_ai.core.errors import PortMissing
from hiru_ai.core.ports import (
    CanonStore,
    ChatStore,
    DirectorStore,
    DocStore,
    Files,
    FrameStore,
    ImageGen,
    Jobs,
    MemoryStore,
    ProducerStore,
    RevisionStore,
    SceneStore,
    Search,
    SplitStore,
    Staging,
    StructureStore,
)
from hiru_ai.core.telemetry import ToolEvent
from hiru_ai.core.usage import UsageRow, UsageSink


@dataclass(frozen=True)
class Ports:
    scenes: SceneStore | None = None
    canon: CanonStore | None = None
    structure: StructureStore | None = None
    docs: DocStore | None = None
    memory: MemoryStore | None = None
    search: Search | None = None
    files: Files | None = None
    frames: FrameStore | None = None
    split: SplitStore | None = None
    producer: ProducerStore | None = None
    director: DirectorStore | None = None
    revisions: RevisionStore | None = None
    images: ImageGen | None = None
    jobs: Jobs | None = None
    staging: Staging | None = None
    chat: ChatStore | None = None  # a production assistant's thread (Sable, plan/2026-11-08)


@dataclass(frozen=True)
class RunContext:
    production_id: UUID | None = None
    actor_user_id: UUID | None = None
    job_id: UUID | None = None
    usage_sink: UsageSink | None = None
    ports: Ports = field(default_factory=Ports)
    strict: bool = False  # tests: turn warnings (a drifting prompt prefix) into errors
    # What retrieval may search, decided by the caller from trusted data (CLAUDE.md "AI and RAG"): never by a model.
    corpora: tuple[str, ...] = ()
    document_ids: tuple[str, ...] | None = None  # None = every ready document of the production
    # The scene in scope and the person's own words, from the trusted payload (plan/2026-11-04 §4.4): a tool defaults to
    # this scene and checks dialogue against these words, so a model chooses neither.
    scene_id: UUID | None = None
    said: str = ""  # everything the person wrote that a spoken line may use; "" = nothing (a dialogue op is refused)
    # Add the per-component columns (component, component_version, prompt_hash, tool_calls, tool_result_tokens) to the
    # `token_usage` rows of this run. Off until the database is on schema v10; evals turn it on for their own sink.
    usage_detail: bool = False
    # Add `scene_id` (the scene in scope, if any) to the `token_usage` rows of this run (schema v17, plan/2026-11-06d).
    # Off until the database has the column, for the same reason as `usage_detail`.
    usage_scene: bool = False
    # One event per tool call, appended by `tooling.from_part`; scripted evals and the review loop read them back.
    tool_events: list[ToolEvent] = field(default_factory=list, compare=False, repr=False)
    # The passages a search tool handed the model, as `{chunk_id, label}`: the reply cites them like any other search.
    citations: list[dict[str, str]] = field(default_factory=list, compare=False, repr=False)
    # What the `production_memory` middleware loaded for this run (the production's entries, its canon names): read once
    # per run, then reused by every agent call of it (plan/2026-11-05d M5).
    memory_cache: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)
    # What the `tiering` middleware decided for this run (plan/2026-11-08 §4.4): {tier_start, tier_end, escalated_by,
    # reason}. Empty when the agent does not tier.
    tiering: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def need(self, port: str, kind: str = "") -> Any:
        """A port of this run, or a clear error naming the one that is missing."""
        found = getattr(self.ports, port, None)
        if found is None:
            raise PortMissing(f"this run has no {port!r} port{f' ({kind})' if kind else ''}; "
                              "the composition root builds it (adapters or fakes)")
        return found

    @property
    def thread_id(self) -> str:
        """Checkpoints are keyed by job, so a re-delivered job resumes where it stopped."""
        return str(self.job_id) if self.job_id else "adhoc"

    def usage_row(self, usage: UsageRow) -> UsageRow:
        """A `token_usage` row with the run's ids added (the table's own columns)."""
        row = {**usage,
               "job_id": str(self.job_id) if self.job_id else None,
               "production_id": str(self.production_id) if self.production_id else None,
               "actor_user_id": str(self.actor_user_id) if self.actor_user_id else None}
        if self.usage_scene and self.scene_id:
            row["scene_id"] = str(self.scene_id)
        return row

    def sink(self) -> UsageSink | None:
        """The usage sink with the run's ids added to every row."""
        inner = self.usage_sink
        if inner is None:
            return None
        return lambda usage: inner(self.usage_row(usage))
