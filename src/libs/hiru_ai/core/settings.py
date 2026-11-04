"""Settings, read once through `get_settings()` (nested environment variables use `__`).

The names are the ones the functions and the API already use (`OPENAI__API_KEY`, `OPENAI__MODEL_HIGH`,
`SUPABASE__URL`...), so moving a function onto hiru_ai changes no deployment configuration.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, SecretStr
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
    model_medium: str = "gpt-5-mini"
    effort_medium: str = "low"
    model_low: str = "gpt-5-nano"
    effort_low: str = "minimal"
    model_vision: str = "gpt-5-mini"  # looks at pictures (the frame check); no reasoning effort
    model_image: str = "gpt-image-2"
    image_quality: str = "medium"
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 1536  # must match chunks.embedding vector(1536)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key.get_secret_value())


class SupabaseSettings(BaseModel):
    url: str = "http://127.0.0.1:54321"
    service_role_key: SecretStr = SecretStr("")
    db_url: str = ""  # direct Postgres URL for durable graph checkpoints; empty = in-memory


class AISettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="__", extra="ignore", case_sensitive=False)

    environment: str = "local"
    # Write the per-component columns of `token_usage` (component, component_version, prompt_hash, tool_calls,
    # tool_result_tokens: schema v10). Off until the database has them, so a row never names a column it lacks.
    usage_detail: bool = False
    # Agents that run as a tool loop (their manifest's `with_tools` form), as a comma-separated list of ids. Empty =
    # none: an agent switches only after a live A/B says it is at least as good (plan/2026-11-04 §8). Going back is
    # removing the id.
    agent_tools: str = ""
    openai: OpenAISettings = OpenAISettings()
    supabase: SupabaseSettings = SupabaseSettings()


@lru_cache
def get_settings() -> AISettings:
    return AISettings()


def agents_with_tools() -> frozenset[str]:
    """The ids named in `AGENT_TOOLS`: the agents that run as a tool loop (their manifest's `with_tools` form)."""
    return frozenset(x.strip() for x in get_settings().agent_tools.split(",") if x.strip())
