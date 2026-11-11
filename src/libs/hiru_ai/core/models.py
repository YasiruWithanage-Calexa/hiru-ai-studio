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
PINS_YAML = Path(__file__).with_name("raphael_models.yaml")  # the model and effort of the tiers that are fixed in code


class TierSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # name of an OpenAISettings field holding the model id. "" = the tier's model and effort are FIXED in
    # `raphael_models.yaml` (configuration, not environment); `load_models` refuses a tier that has neither.
    model: str = ""
    effort: str = ""  # name of an OpenAISettings field holding the reasoning effort ("" = none)
    timeout_s: float = 120
    retries: int = Field(2, ge=0)
    fallbacks: list[str] = []
    # A conversation on this tier goes through the Responses API with `previous_response_id`, so a reasoning
    # model's reasoning carries from turn to turn (plan/2026-11-08f §5). Off: Chat Completions, as before.
    responses: bool = False


EFFORTS: tuple[str, ...] = ("minimal", "low", "medium", "high")


class Pin(BaseModel):
    """One fixed tier: the OpenAI model id and the reasoning effort, as written in `raphael_models.yaml`."""

    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    effort: str

    def model_post_init(self, __context: Any) -> None:
        if self.effort not in EFFORTS:
            raise ValueError(f"effort {self.effort!r} is not one of {', '.join(EFFORTS)}")


class PinsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tiers: dict[str, Pin]


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
    responses: bool = False


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
    if path == MODELS_YAML:  # a tier with no settings field must be fixed in the pins file, and only those
        pins = load_pins()
        fixed = {n for n, s in file.tiers.items() if not s.model}
        for name in sorted(fixed - set(pins)):
            raise ManifestError(f"{path}: tier {name!r} names no setting, so {PINS_YAML.name} must fix its model")
        for name in sorted(set(pins) - fixed):
            raise ManifestError(f"{PINS_YAML.name}: {name!r} is not a tier without a setting in models.yaml")
    return file


@lru_cache
def load_pins(path: Path = PINS_YAML) -> dict[str, Pin]:
    """The tiers whose model and effort are fixed in the repository (`raphael_models.yaml`), not in the environment."""
    try:
        return PinsFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))).tiers
    except (OSError, ValueError) as exc:
        raise ManifestError(f"{path}: {exc}") from exc


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
    if not spec.model:  # fixed in raphael_models.yaml: the environment cannot change it
        pin = load_pins().get(name)
        if pin is None:
            raise ManifestError(f"tier {name!r} names no setting and {PINS_YAML.name} does not fix it")
        return Tier(name=name, model=pin.model, effort=pin.effort, timeout_s=spec.timeout_s, retries=spec.retries,
                    fallbacks=tuple(spec.fallbacks), responses=spec.responses)
    return Tier(name=name, model=str(_setting(settings, spec.model)),
                effort=str(_setting(settings, spec.effort)) if spec.effort else "",
                timeout_s=spec.timeout_s, retries=spec.retries, fallbacks=tuple(spec.fallbacks),
                responses=spec.responses)
