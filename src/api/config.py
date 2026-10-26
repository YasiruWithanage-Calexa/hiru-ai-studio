"""API settings. Loaded once: always call `get_settings()`, never instantiate `Settings()`.

Priority: environment variables > `.env` > defaults. Nested fields use `__`
(`SUPABASE__URL` → `settings.supabase.url`). In production every secret arrives as an
environment variable bound from Secret Manager by Cloud Run; there is no `.env` in the image.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import BaseModel, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class SupabaseSettings(BaseModel):
    url: str = "http://127.0.0.1:54321"
    service_role_key: SecretStr = SecretStr("")
    # Only for projects still signing with the legacy shared secret (HS256). Projects on
    # asymmetric signing keys verify against the published JWKS and leave this empty.
    jwt_secret: SecretStr = SecretStr("")
    invite_redirect_url: str = "http://localhost:3000/auth/accept"


class ApiSettings(BaseModel):
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    public_url: str = "http://localhost:8000"
    internal_secret: SecretStr = SecretStr("")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


class GcpSettings(BaseModel):
    project_id: str = ""
    region: str = "asia-south1"
    tasks_queue: str = "hiru-jobs"
    tasks_invoker_sa: str = ""
    # "{function_name}" is substituted when present, else the name is appended as a path.
    functions_base_url: str = ""


class OpenAISettings(BaseModel):
    """OpenAI is the only LLM provider (PLAN.md §5). Empty key = AI features off: search runs
    keyword-only and nothing is reranked, so the app is fully testable without a key."""

    api_key: SecretStr = SecretStr("")
    model_medium: str = "gpt-5-mini"  # reranking
    effort_medium: str = "low"
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 1536  # must match chunks.embedding vector(1536)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key.get_secret_value())


class AssembleSettings(BaseModel):
    """The ffmpeg service (infra/assemble): a take's last frame and its probe. Empty URL: takes
    are still accepted, and the carried frame is reported as not made."""

    url: str = ""
    secret: SecretStr = SecretStr("")


class UsageSettings(BaseModel):
    """The top-bar usage meter: model tokens used this month as a share of this budget."""

    monthly_token_budget: int = 5_000_000


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_nested_delimiter="__", extra="ignore", case_sensitive=False
    )

    environment: Literal["local", "test", "staging", "prod"] = "local"
    local_functions: bool = True
    supabase: SupabaseSettings = SupabaseSettings()
    api: ApiSettings = ApiSettings()
    gcp: GcpSettings = GcpSettings()
    openai: OpenAISettings = OpenAISettings()
    usage: UsageSettings = UsageSettings()
    assemble: AssembleSettings = AssembleSettings()


@lru_cache
def get_settings() -> Settings:
    return Settings()
