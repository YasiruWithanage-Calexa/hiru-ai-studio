"""Function settings, read from the environment once (Secret Manager → env on Cloud Run).

This function runs no LLM: it calls a Google video model, stores the result and writes rows. The Google key is read
here and nowhere else (plan/2026-11-06c §2.1: Google is for rendering a take and nothing else)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache


def _json_dict(raw: str) -> dict[str, str]:
    try:
        value = json.loads(raw) if raw.strip() else {}
    except ValueError:
        return {}
    return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}


def _int_dict(raw: str) -> dict[str, int]:
    return {k: int(v) for k, v in _json_dict(raw).items() if v.lstrip("-").isdigit()}


@dataclass(frozen=True)
class Config:
    supabase_url: str
    service_role_key: str
    api_internal_url: str
    internal_secret: str
    google_api_key: str
    # The generative-language REST host; overridable so a spike can point at another endpoint without a redeploy.
    google_base_url: str = "https://generativelanguage.googleapis.com"
    # engine key → model id sent instead of the capability row's (`VIDEO__MODELS='{"veo_3_1":"veo-3.1-generate-002"}'`).
    models: dict[str, str] = field(default_factory=dict)
    # CI and localhost only: every engine returns a generated placeholder and nobody is called.
    fake_provider: bool = False
    # How long one render may take end to end. Must stay under the function's own timeout (1800 s).
    take_timeout_s: int = 1680
    # A re-delivered task finding a render still `running` with a provider id may resume polling it, but only once the
    # first invocation is certainly gone, i.e. this long after the submit.
    resume_after_s: int = 1800
    max_resumes: int = 2
    poll_interval_s: float = 5.0
    # A generation that succeeded has already cost money, so retrieval is retried to exhaustion.
    download_attempts: int = 5
    # D3 (plan/2026-11-06c): Veo reports seconds, not tokens. A hidden per-second token equivalent per engine keeps the
    # one usage percentage honest (`VIDEO__TOKENS_PER_SECOND='{"veo_3_1":12000}'`). 0 = counts nothing until it is set.
    tokens_per_second: dict[str, int] = field(default_factory=dict)

    @property
    def can_render(self) -> bool:
        return self.fake_provider or bool(self.google_api_key)


@lru_cache
def get_config() -> Config:
    env = os.environ.get
    return Config(
        supabase_url=env("SUPABASE__URL", "http://127.0.0.1:54321"),
        service_role_key=env("SUPABASE__SERVICE_ROLE_KEY", ""),
        api_internal_url=env("API__INTERNAL_URL", "http://localhost:8000"),
        internal_secret=env("API__INTERNAL_SECRET", ""),
        google_api_key=env("GOOGLE__API_KEY", ""),
        google_base_url=env("GOOGLE__BASE_URL", "https://generativelanguage.googleapis.com"),
        models=_json_dict(env("VIDEO__MODELS", "")),
        fake_provider=env("VIDEO__FAKE_PROVIDER", "").lower() in ("1", "true", "yes"),
        take_timeout_s=int(env("VIDEO__TAKE_TIMEOUT_S", "1680")),
        resume_after_s=int(env("VIDEO__RESUME_AFTER_S", "1800")),
        max_resumes=int(env("VIDEO__MAX_RESUMES", "2")),
        poll_interval_s=float(env("VIDEO__POLL_INTERVAL_S", "5")),
        download_attempts=int(env("VIDEO__DOWNLOAD_ATTEMPTS", "5")),
        tokens_per_second=_int_dict(env("VIDEO__TOKENS_PER_SECOND", "")),
    )
