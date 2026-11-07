"""Function settings, read from the environment once (Secret Manager → env on Cloud Run)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Config:
    supabase_url: str
    service_role_key: str
    openai_api_key: str
    # Tiers (PLAN.md §5). Model ids are configuration; confirm the current line-up per release.
    model_medium: str
    model_low: str
    effort_medium: str
    effort_low: str
    embedding_model: str
    embedding_dimensions: int
    # The document reader (plan/2026-11-06f): the author's model at its own effort. Off until a person turns it on
    # after the live eval (READER__ENABLED); then `documents.reading_path` / `read_from` must exist (schema v16).
    model_reader: str = "gpt-5"
    effort_reader: str = "medium"
    reader_enabled: bool = False
    reader_workers: int = 4

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache
def get_config() -> Config:
    env = os.environ.get
    return Config(
        supabase_url=env("SUPABASE__URL", "http://127.0.0.1:54321"),
        service_role_key=env("SUPABASE__SERVICE_ROLE_KEY", ""),
        openai_api_key=env("OPENAI__API_KEY", ""),
        model_medium=env("OPENAI__MODEL_MEDIUM", "gpt-5-mini"),
        model_low=env("OPENAI__MODEL_LOW", "gpt-5-nano"),
        effort_medium=env("OPENAI__EFFORT_MEDIUM", "low"),
        effort_low=env("OPENAI__EFFORT_LOW", "minimal"),
        embedding_model=env("OPENAI__EMBEDDING_MODEL", "text-embedding-3-large"),
        embedding_dimensions=int(env("OPENAI__EMBEDDING_DIMENSIONS", "1536")),
        model_reader=env("OPENAI__MODEL_AUTHOR", "gpt-5"),
        effort_reader=env("OPENAI__EFFORT_READER", "medium"),
        reader_enabled=env("READER__ENABLED", "").strip().lower() in ("1", "true", "yes", "on"),
        reader_workers=int(env("READER__WORKERS", "4")),
    )
