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
    )
