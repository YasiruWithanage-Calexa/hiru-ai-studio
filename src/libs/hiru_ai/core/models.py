"""models.yaml → resolved tiers. Pure data; no network and no LangChain."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from hiru_ai.core.errors import ManifestError
from hiru_ai.core.settings import AISettings, get_settings

MODELS_YAML = Path(__file__).with_name("models.yaml")


class TierSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str  # name of an OpenAISettings field holding the model id
    effort: str = ""  # name of an OpenAISettings field holding the reasoning effort ("" = none)
    timeout_s: float = 120
    retries: int = Field(2, ge=0)
    fallbacks: list[str] = []


class EmbedSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    dimensions: str
    timeout_s: float = 60
    retries: int = Field(2, ge=0)


class ImageSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    quality: str = ""
    draft_quality: str = ""  # name of the setting holding the quality of a draft ("" = the same as `quality`)


class ModelsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tiers: dict[str, TierSpec]
    embed: EmbedSpec
    image: ImageSpec


@dataclass(frozen=True)
class Tier:
    name: str
    model: str
    effort: str
    timeout_s: float
    retries: int
    fallbacks: tuple[str, ...]


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """`over` laid on `base`, mappings merged key by key and everything else replaced."""
    out = dict(base)
    for key, value in over.items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def overlay_path(path: Path, env: str) -> Path:
    """`models.yaml` -> `models.<env>.yaml` beside it."""
    return path.with_name(f"{path.stem}.{env}{path.suffix}")


@lru_cache
def load_models(path: Path = MODELS_YAML, env: str | None = None) -> ModelsFile:
    """The tiers, with `models.<env>.yaml` laid over them when the environment (`HIRU_AI__ENV`, else `ENVIRONMENT`)
    has one: a staging tier that falls back, a cheaper model for a dev run. Nothing else changes per environment."""
    if env is None:
        env = os.environ.get("HIRU_AI__ENV") or os.environ.get("ENVIRONMENT") or ""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        extra = overlay_path(path, env) if env else None
        if extra is not None and extra.is_file():
            data = _merge(data, yaml.safe_load(extra.read_text(encoding="utf-8")) or {})
        file = ModelsFile.model_validate(data)
    except (OSError, ValueError) as exc:
        raise ManifestError(f"{path}: {exc}") from exc
    for name, spec in file.tiers.items():
        for fb in spec.fallbacks:
            if fb not in file.tiers or fb == name:
                raise ManifestError(f"{path}: tier {name!r} falls back to unknown tier {fb!r}")
    return file


def tier_names() -> list[str]:
    return list(load_models().tiers)


def _setting(settings: AISettings, field: str) -> Any:
    if field not in type(settings.openai).model_fields:
        raise ManifestError(f"models.yaml names an unknown OpenAI setting {field!r}")
    return getattr(settings.openai, field)


def resolve(name: str, settings: AISettings | None = None, models: ModelsFile | None = None) -> Tier:
    settings = settings or get_settings()
    models = models or load_models()
    if name not in models.tiers:
        raise ManifestError(f"unknown model tier {name!r}; known: {', '.join(models.tiers)}")
    spec = models.tiers[name]
    return Tier(name=name, model=str(_setting(settings, spec.model)),
                effort=str(_setting(settings, spec.effort)) if spec.effort else "",
                timeout_s=spec.timeout_s, retries=spec.retries, fallbacks=tuple(spec.fallbacks))
