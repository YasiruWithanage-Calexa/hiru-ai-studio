"""Function settings, read from the environment once (Secret Manager → env on Cloud Run)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Tier:
    model: str
    effort: str


@dataclass(frozen=True)
class Config:
    supabase_url: str
    service_role_key: str
    openai_api_key: str
    # Tiers (PLAN.md §5). Model ids are configuration; confirm the current line-up per release.
    tiers: dict[str, Tier]
    # The courier: where a finished hop asks for the next one (POST /internal/pipeline/advance).
    api_internal_url: str
    internal_secret: str

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key)


def tiers_from_env() -> dict[str, Tier]:
    env = os.environ.get
    return {
        "ultra": Tier(env("OPENAI__MODEL_ULTRA", "gpt-5"), env("OPENAI__EFFORT_ULTRA", "high")),
        "high": Tier(env("OPENAI__MODEL_HIGH", "gpt-5"), env("OPENAI__EFFORT_HIGH", "medium")),
        "medium": Tier(env("OPENAI__MODEL_MEDIUM", "gpt-5-mini"), env("OPENAI__EFFORT_MEDIUM", "low")),
        "low": Tier(env("OPENAI__MODEL_LOW", "gpt-5-nano"), env("OPENAI__EFFORT_LOW", "minimal")),
    }


@lru_cache
def get_config() -> Config:
    env = os.environ.get
    return Config(
        supabase_url=env("SUPABASE__URL", "http://127.0.0.1:54321"),
        service_role_key=env("SUPABASE__SERVICE_ROLE_KEY", ""),
        openai_api_key=env("OPENAI__API_KEY", ""),
        tiers=tiers_from_env(),
        api_internal_url=env("API__INTERNAL_URL", "http://localhost:8000"),
        internal_secret=env("API__INTERNAL_SECRET", ""),
    )
