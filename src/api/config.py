"""API settings. Loaded once: always call `get_settings()`, never instantiate `Settings()`.

Priority: environment variables > `.env` > defaults. Nested fields use `__`
(`SUPABASE__URL` → `settings.supabase.url`). In production every secret arrives as an
environment variable bound from Secret Manager by Cloud Run; there is no `.env` in the image.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from typing_extensions import Annotated


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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_nested_delimiter="__", extra="ignore", case_sensitive=False
    )

    environment: Literal["local", "test", "staging", "prod"] = "local"
    local_functions: bool = True
    supabase: SupabaseSettings = SupabaseSettings()
    api: ApiSettings = ApiSettings()
    gcp: GcpSettings = GcpSettings()


@lru_cache
def get_settings() -> Settings:
    return Settings()
