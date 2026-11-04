"""The one door to models: `get_llm(tier)` and `get_structured(tier, Schema)`.

Everything in hiru_ai asks here for a model; nothing else imports OpenAI or LangChain's OpenAI package. The
gateway behind the door is `ChatOpenAI` (ADR 0003). Swapping it (LiteLLM, say) changes this file and
`usage.py` only, because callers hold a LangChain `BaseChatModel`.

What the door promises, each checked in tests/hiru_ai/test_llm.py:
  * strict JSON-schema structured output; messages are sent exactly as given (OpenAI's prompt cache keys on the
    leading bytes, so nothing here may rewrite them)
  * `reasoning_effort` per tier, retries and a timeout per tier, optional fallback tiers
  * token counts also on streamed calls (`stream_usage`)
  * no key: `ModelUnavailable` (callers degrade, "absent-safe"); tests never touch the network
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable

from hiru_ai.core.errors import ModelUnavailable
from hiru_ai.core.models import Tier, load_models, resolve
from hiru_ai.core.settings import AISettings, get_settings
from hiru_ai.core.usage import UsageSink, row, safely

# Tests replace the models for the length of a `with use_models(...)` block.
_override: ContextVar[Callable[[Tier], BaseChatModel] | None] = ContextVar("hiru_ai_models", default=None)


@contextmanager
def use_models(models: BaseChatModel | Callable[[Tier], BaseChatModel]) -> Iterator[None]:
    """Make `get_llm` return fakes inside the block: one model, or a function of the resolved tier."""
    factory: Callable[[Tier], BaseChatModel]
    if isinstance(models, BaseChatModel):
        fixed = models
        factory = lambda tier: fixed  # noqa: E731
    else:
        factory = models
    token = _override.set(factory)
    try:
        yield
    finally:
        _override.reset(token)


_embeddings_override: ContextVar[Callable[[str, UsageSink | None], Embeddings] | None] = ContextVar(
    "hiru_ai_embeddings", default=None)


@contextmanager
def use_embeddings(factory: Callable[[str, UsageSink | None], Embeddings]) -> Iterator[None]:
    """Make `get_embeddings` return `factory(phase, sink)` inside the block (tests)."""
    token = _embeddings_override.set(factory)
    try:
        yield
    finally:
        _embeddings_override.reset(token)


def models_enabled(settings: AISettings | None = None) -> bool:
    """True when a call can be made: a key is set (or a test supplied models)."""
    return (_override.get() is not None or _embeddings_override.get() is not None
            or (settings or get_settings()).openai.enabled)


def _chat(tier: Tier, settings: AISettings, callbacks: list[BaseCallbackHandler] | None,
          http_client: Any) -> BaseChatModel:
    from langchain_openai import ChatOpenAI
    from pydantic import SecretStr

    kwargs: dict[str, Any] = {}
    if tier.effort:
        kwargs["reasoning_effort"] = tier.effort
    if settings.openai.base_url:
        kwargs["base_url"] = settings.openai.base_url
    if http_client is not None:
        kwargs["http_client"] = http_client
    return ChatOpenAI(model=tier.model, api_key=SecretStr(settings.openai.api_key.get_secret_value() or "unset"),
                      timeout=tier.timeout_s, max_retries=tier.retries,
                      stream_usage=True,  # a streamed call still reports its tokens
                      callbacks=callbacks, **kwargs)


def get_llm(tier: str, *, settings: AISettings | None = None, callbacks: list[BaseCallbackHandler] | None = None,
            http_client: Any = None) -> BaseChatModel:
    """The chat model for a tier. Raises `ModelUnavailable` without a key."""
    settings = settings or get_settings()
    resolved = resolve(tier, settings)
    fake = _override.get()
    if fake is not None:
        return fake(resolved)
    if not settings.openai.enabled:
        raise ModelUnavailable("OPENAI__API_KEY is not set")
    return _chat(resolved, settings, callbacks, http_client)


def get_structured(tier: str, schema: Any, *, settings: AISettings | None = None,
                   callbacks: list[BaseCallbackHandler] | None = None, http_client: Any = None) -> Runnable[Any, Any]:
    """A runnable that answers with `schema` (a pydantic class; strict JSON-schema output).

    The tier's `fallbacks` (models.yaml) are tried in order after the model fails.
    """
    settings = settings or get_settings()

    def build(name: str) -> Runnable[Any, Any]:
        model = get_llm(name, settings=settings, callbacks=callbacks, http_client=http_client)
        return model.with_structured_output(schema, method="json_schema", strict=True)

    primary = build(tier)
    fallbacks = [build(name) for name in resolve(tier, settings).fallbacks]
    return primary.with_fallbacks(fallbacks) if fallbacks else primary


class UsageEmbeddings(Embeddings):
    """Embeddings that also report the tokens used. LangChain's own wrapper drops them and the subscription meter
    needs them, so this uses the `openai` SDK directly, as the services do today."""

    def __init__(self, phase: str, sink: UsageSink | None, settings: AISettings | None = None,
                 client: Any = None) -> None:
        self.settings = settings or get_settings()
        self.phase = phase
        self.sink = sink
        spec = load_models().embed
        self.model = str(getattr(self.settings.openai, spec.model))
        self.dimensions = int(getattr(self.settings.openai, spec.dimensions))
        self.timeout_s, self.retries = spec.timeout_s, spec.retries
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            if not self.settings.openai.enabled:
                raise ModelUnavailable("OPENAI__API_KEY is not set")
            from openai import OpenAI

            self._client = OpenAI(api_key=self.settings.openai.api_key.get_secret_value(),
                                  base_url=self.settings.openai.base_url or None,
                                  timeout=self.timeout_s, max_retries=self.retries)
        return self._client

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        resp = self.client.embeddings.create(model=self.model, input=texts, dimensions=self.dimensions)
        safely(self.sink, row(self.phase, self.model, resp.usage.prompt_tokens if resp.usage else 0))
        return [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def get_embeddings(phase: str, sink: UsageSink | None = None, *, settings: AISettings | None = None,
                   client: Any = None) -> Embeddings:
    fake = _embeddings_override.get()
    if fake is not None and client is None:
        return fake(phase, sink)
    return UsageEmbeddings(phase, sink, settings, client)


def image_model(settings: AISettings | None = None) -> tuple[str, str]:
    """(model id, quality) of the `image` entry in models.yaml."""
    settings = settings or get_settings()
    spec = load_models().image
    return str(getattr(settings.openai, spec.model)), str(getattr(settings.openai, spec.quality))


def openai_client(settings: AISettings | None = None, *, timeout_s: float = 180.0, retries: int = 0) -> Any:
    """The raw `openai` SDK client, for the calls LangChain has no wrapper for (pictures). Same key and base URL as
    the chat tiers; no key raises `ModelUnavailable`. Adapters take this from here so that `core.llm` stays the one
    module that imports OpenAI."""
    settings = settings or get_settings()
    if not settings.openai.enabled:
        raise ModelUnavailable("OPENAI__API_KEY is not set")
    from openai import OpenAI

    return OpenAI(api_key=settings.openai.api_key.get_secret_value(), base_url=settings.openai.base_url or None,
                  timeout=timeout_s, max_retries=retries)
