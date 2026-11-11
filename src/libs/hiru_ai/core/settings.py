"""Settings, read once through `get_settings()` (nested environment variables use `__`).

The names are the ones the functions and the API already use (`OPENAI__API_KEY`, `OPENAI__MODEL_HIGH`,
`SUPABASE__URL`...), so moving a function onto hiru_ai changes no deployment configuration.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import BaseModel, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class OpenAISettings(BaseModel):
    """OpenAI is the only provider (ADR 0002). An empty key means AI features are off."""

    api_key: SecretStr = SecretStr("")
    base_url: str = ""  # tests and proxies; empty = OpenAI
    # Tiers: model ids are configuration, not code. models.yaml says which setting each tier reads.
    model_ultra: str = "gpt-5"
    effort_ultra: str = "high"
    model_high: str = "gpt-5"
    effort_high: str = "medium"
    effort_fixer: str = "low"  # the `fixer` tier is model_high at this effort (Shot Planner Adam's top fixer rung)
    # Shot Planner David (plan/2026-11-05e §4.2): the author and the repairer use one model; the spike decides which
    # (D3). Changing it is an environment change, not a code change.
    model_author: str = "gpt-5"
    effort_author: str = "medium"
    effort_repair: str = "low"
    # The document reader (plan/2026-11-06f Q1): the `reader` tier is model_author at this effort. Reading is less
    # creative than planning; the live eval (`scripts/eval_reader.py --yes`) decides.
    effort_reader: str = "medium"
    # The scene breakdown (plan/2026-11-11 §9): the `breakdown` tier (split, continuity, episodes, repair, stager). The
    # lab ran every step on GPT-6.1 Sol at medium; whether continuity and episodes need high is for the live check.
    model_breakdown: str = "gpt-6.1-sol"
    effort_breakdown: str = "medium"
    # Shot Planner Jonathan (plan/2026-11-06b): the `jonathan` tier, its own model (gpt-5 shuts down 2026-12-11;
    # GPT-6.1 Sol is OpenAI's near-flagship at gpt-5's price class) at the effort the cinematic lab proved (high).
    # An environment change, not a code change.
    model_jonathan: str = "gpt-6.1-sol"
    effort_jonathan: str = "high"
    # Raphael's models are NOT settings: the model and effort of its five tiers are fixed in raphael_models.yaml
    # (configuration, reviewed in a commit; nothing in the environment changes them).
    # Zora's author (plan/2026-11-06e D7): the `zora` tier is model_jonathan at this effort; the lab sets it.
    effort_zora: str = "low"
    # Sable (plan/2026-11-08 §4.4, D2): the average tier and the deep tier a turn may move up to once. Until the lab
    # picks the pair: gpt-5-mini at low, and gpt-5 at medium. An environment change, not a code change.
    model_sable: str = "gpt-5-mini"
    effort_sable: str = "low"
    model_sable_deep: str = "gpt-5"
    effort_sable_deep: str = "medium"
    model_medium: str = "gpt-5-mini"
    effort_medium: str = "low"
    model_low: str = "gpt-5-nano"
    effort_low: str = "minimal"
    model_vision: str = "gpt-5-mini"  # looks at pictures (the frame check); no reasoning effort
    model_image: str = "gpt-image-2"
    image_quality: str = "medium"  # a final first frame
    image_quality_draft: str = "low"  # a draft first frame: cheap, to settle the picture before the final is painted
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 1536  # must match chunks.embedding vector(1536)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key.get_secret_value())


class ZoraSettings(BaseModel):
    """Zora, the director chat over Jonathan's plan (plan/2026-11-06e Phase 4): `ZORA__*`. Off until a person turns it
    on (D3); the numbers are the plan's."""

    enabled: bool = False
    max_repairs: int = 2  # repair passes after the planner's checks (§4.6 step 4)
    delivery_passes: int = 1  # re-tasks for declared effects that did not change (§4.6 step 5)
    reshape_dirty_ratio: float = 0.5  # an edit that rewrites more than this share of the shots is offered as a re-plan
    reshape_min_shots: int = 3
    variants_max: int = 3
    author_tool_calls: int = 6  # the author's read tools, when it has a `with_tools` form (none in v1)
    transcript_messages: int = 4
    revisions_kept: int = 30  # undo depth per scene (D4)


class SableSettings(BaseModel):
    """Sable, the production assistant chat (plan/2026-11-08): `SABLE__*`. Off until a person turns it on (Phase 8)."""

    enabled: bool = False
    history_messages: int = 12  # the last messages sent whole (§4.5)
    summary_after_tokens: int = 6000  # older messages are summarised once the thread passes this (§4.5)


class ReaderSettings(BaseModel):
    """The document reader (plan/2026-11-06f): `READER__*`. Off until a person turns it on after the live eval
    (Phase 5): with it off, ingest reads no document with a model and every build is as before."""

    enabled: bool = False
    workers: int = 4  # episode calls at once


class BreakdownSettings(BaseModel):
    """The scene breakdown (plan/2026-11-11): `BREAKDOWN__*`. Off until a person turns it on after the live check
    (phase 7): with it off, creation builds the structure as before and no planner reads a packet."""

    enabled: bool = False
    workers: int = 4  # documents and episode calls at once (plan §10, phase 2)


class SupabaseSettings(BaseModel):
    url: str = "http://127.0.0.1:54321"
    service_role_key: SecretStr = SecretStr("")
    db_url: str = ""  # direct Postgres URL for durable graph checkpoints; empty = in-memory


class AISettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="__", extra="ignore", case_sensitive=False)

    environment: str = "local"
    # Write the per-component columns of `token_usage` (component, component_version, prompt_hash, tool_calls,
    # tool_result_tokens: schema v10; reasoning_tokens: schema v12). Off until the database has them, so a row never
    # names a column it lacks.
    usage_detail: bool = False
    # Write `token_usage.scene_id` (schema v17, plan/2026-11-06d): the scene a call was for, so a scene's cost counts
    # the director chat's work on it. Off until `Database/upgrade_v16_to_v17.sql` has been run, for the same reason.
    usage_scene: bool = False
    # How Shot Planner Adam plans a scene: `staged` (five gpt-5 stages and four critics, plan/2026-11-04b) or `take`
    # (one gpt-5 call for the plan and a ladder of small-model fixes, plan/2026-11-05). `staged` until a person has
    # judged the two side by side (plan/2026-11-05 §7) and chosen.
    adam_mode: str = "staged"
    # How many scenes Adam plans at once in one delivery (plan/2026-11-05b). A staged scene is about 40,000 gpt-5 output
    # tokens over ~11 minutes, so ten at once is far under the per-minute limits of a paid tier; lower it if the
    # account's are low. A setting, not code: changing it is an environment change.
    adam_workers: int = 10
    # How many scenes David plans at once in one delivery (plan/2026-11-05e §4.4); a chain of linked scenes is one
    # worker.
    david_workers: int = 10
    # The same for Shot Planner Jonathan (plan/2026-11-06b).
    jonathan_workers: int = 10
    # The same for Shot Planner Raphael (plan/2026-11-08e): scenes at once in one delivery.
    raphael_workers: int = 10
    # Shot Planner Raphael's money limit for ONE scene, both stages together (plan/2026-11-08f §4). The lab ran with $5;
    # a healthy scene cost $0.58-0.75 there, and a stuck one $1.50 live (2026-11-08). At the limit the scene stops and
    # keeps what it wrote. A setting, not code.
    raphael_scene_cap_usd: float = 1.00
    # plan/2026-11-10: Raphael writes a director's breakdown of the scene first, then builds from it.
    # false = Raphael exactly as it was before the breakdown.
    raphael_breakdown: bool = True
    # plan/2026-11-11 phase 4: Raphael's first agent reads the stored scene packet (the whole packet is its first
    # message) when the scene has a complete one. false = today's message. Off until the live check.
    raphael_packet: bool = False
    # Agents that run as a tool loop (their manifest's `with_tools` form), as a comma-separated list of ids. Empty =
    # none: an agent switches only after a live A/B says it is at least as good (plan/2026-11-04 §8). Going back is
    # removing the id.
    agent_tools: str = ""
    openai: OpenAISettings = OpenAISettings()
    supabase: SupabaseSettings = SupabaseSettings()
    zora: ZoraSettings = ZoraSettings()
    reader: ReaderSettings = ReaderSettings()
    breakdown: BreakdownSettings = BreakdownSettings()
    sable: SableSettings = SableSettings()
    # Where traces go (ADR 0008: Langfuse Cloud). Langfuse's own names, as its settings page prints them. Empty keys =
    # no tracing.
    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr = SecretStr("")
    langfuse_base_url: str = "https://cloud.langfuse.com"

    @field_validator("langfuse_public_key", "langfuse_secret_key", "langfuse_base_url", mode="before")
    @classmethod
    def _unquote(cls, value: Any) -> Any:
        """A launcher that copies `.env` into the environment can keep `KEY="value"`'s quotes; a quoted URL or key
        fails every send without a word."""
        if isinstance(value, str) and len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            return value[1:-1]
        return value

    @property
    def tracing(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key.get_secret_value())


@lru_cache
def get_settings() -> AISettings:
    return AISettings()


def agents_with_tools() -> frozenset[str]:
    """The ids named in `AGENT_TOOLS`: the agents that run as a tool loop (their manifest's `with_tools` form)."""
    return frozenset(x.strip() for x in get_settings().agent_tools.split(",") if x.strip())
