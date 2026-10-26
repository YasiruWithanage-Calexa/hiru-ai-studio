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
    # The `image` tier (PLAN.md §5): the model is configuration, not code.
    image_model: str
    image_quality: str
    api_internal_url: str
    internal_secret: str

    @property
    def images_enabled(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache
def get_config() -> Config:
    env = os.environ.get
    return Config(
        supabase_url=env("SUPABASE__URL", "http://127.0.0.1:54321"),
        service_role_key=env("SUPABASE__SERVICE_ROLE_KEY", ""),
        openai_api_key=env("OPENAI__API_KEY", ""),
        image_model=env("OPENAI__MODEL_IMAGE", "gpt-image-2"),
        image_quality=env("OPENAI__IMAGE_QUALITY", "medium"),
        api_internal_url=env("API__INTERNAL_URL", "http://localhost:8000"),
        internal_secret=env("API__INTERNAL_SECRET", ""),
    )
