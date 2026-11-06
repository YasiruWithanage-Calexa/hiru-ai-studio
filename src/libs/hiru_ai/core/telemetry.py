"""Logging, trace tags and the tracing switch. Tags name the part, its version and its prompt, so a run can be traced
to what ran; they travel as LangChain run metadata. Never put prompts, scripts or keys in a tag.

Traces go to Langfuse Cloud (ADR 0008) once `enable_tracing()` has run with keys set: every LangChain run
(each graph, node and agent call) then lands in one tree per run. Without keys, or without the `langfuse` package,
nothing is traced and nothing changes.
"""
from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from hiru_ai.core.settings import AISettings, get_settings


def logger(name: str) -> logging.Logger:
    return logging.getLogger(f"hiru_ai.{name}")


# LangChain adds a handler to every run while this variable names it (its `register_configure_hook`); the handler
# class is made fresh per top-level run, so one graph run is one trace.
_HOOK_ENV = "HIRU_AI_LANGFUSE"
_enabled = False


def enable_tracing(settings: AISettings | None = None) -> bool:
    """Send every LangChain run in this process to Langfuse. Safe to call more than once; True when tracing is on.

    Off when `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` are unset or the package is missing. A top-level run
    flushes its trace when it ends, so a function that is frozen after replying still delivers it."""
    global _enabled
    if _enabled:
        return True
    if "pytest" in sys.modules:  # tests read the same .env; their fake runs must never reach Langfuse
        return False
    settings = settings or get_settings()
    if not settings.tracing:
        return False
    try:
        from langchain_core.tracers.context import register_configure_hook
        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler
    except ImportError:
        logger("telemetry").warning("LANGFUSE_ keys are set but the langfuse package is not installed: no traces")
        return False

    client = Langfuse(public_key=settings.langfuse_public_key,
                      secret_key=settings.langfuse_secret_key.get_secret_value(),
                      base_url=settings.langfuse_base_url, environment=settings.environment)

    class RunHandler(CallbackHandler):
        """Langfuse's LangChain handler that flushes when the top-level run ends."""

        def on_chain_end(self, outputs: Any, *, run_id: Any, parent_run_id: Any = None, **kwargs: Any) -> Any:
            out = super().on_chain_end(outputs, run_id=run_id, parent_run_id=parent_run_id, **kwargs)
            if parent_run_id is None:
                _flush(client)
            return out

        def on_chain_error(self, error: BaseException, *, run_id: Any, parent_run_id: Any = None,
                           **kwargs: Any) -> Any:
            out = super().on_chain_error(error, run_id=run_id, parent_run_id=parent_run_id, **kwargs)
            if parent_run_id is None:
                _flush(client)
            return out

    os.environ[_HOOK_ENV] = "true"
    register_configure_hook(ContextVar("hiru_ai_langfuse", default=None), True, RunHandler, _HOOK_ENV)
    _enabled = True
    logger("telemetry").info("tracing to Langfuse at %s", settings.langfuse_base_url)
    return True


def _flush(client: Any) -> None:
    try:
        client.flush()
    except Exception:  # a trace that cannot be sent never fails the run
        logger("telemetry").warning("could not send the trace to Langfuse", exc_info=True)


@dataclass(frozen=True)
class ToolEvent:
    """One call of one tool: what the review loop reads (plan/2026-11-04 §9: repeated errors mean a guide or an argument
    needs work, repeated narrow calls mean a bigger default). Never the arguments or the result: those hold the
    script."""

    tool: str
    ms: float
    result_tokens: int
    error: str = ""  # "" = answered; "refused" = the tool said no (it taught); anything else = the lookup failed
    truncated: bool = False  # the result was cut to the tool's budget


@contextmanager
def tool_span(ident: str, version: int, effect: str) -> Iterator[Callable[[ToolEvent], None]]:
    """A span around one tool call (plan/2026-11-04 §9.3, ADR 0008): the tool's id, version and effect, then what the
    call cost. It uses the OpenTelemetry API when the package has it; the API alone exports nothing, so no trace leaves
    until a person installs an exporter (ADR 0008 asks for that decision first). Without OpenTelemetry the span is a
    no-op. The callable it yields records the finished call's numbers on the span; arguments and results are never
    attributes: they hold the script."""
    try:
        from opentelemetry import trace
    except ImportError:  # pragma: no cover - the package is optional
        yield lambda event: None
        return
    with trace.get_tracer("hiru_ai").start_as_current_span(f"tool {ident}") as span:
        span.set_attribute("hiru.tool.id", ident)
        span.set_attribute("hiru.tool.version", version)
        span.set_attribute("hiru.tool.effect", effect)

        def finish(event: ToolEvent) -> None:
            span.set_attribute("hiru.tool.ms", event.ms)
            span.set_attribute("hiru.tool.result_tokens", event.result_tokens)
            span.set_attribute("hiru.tool.error", event.error)
            span.set_attribute("hiru.tool.truncated", event.truncated)

        yield finish


def log_tool_event(event: ToolEvent) -> None:
    logger("tool").info("tool=%s ms=%s result_tokens=%s error=%s truncated=%s", event.tool, event.ms,
                        event.result_tokens, event.error or "-", event.truncated)


@dataclass(frozen=True)
class Tags:
    component: str = ""  # "agent:translator"
    version: int = 0
    prompt_sha: str = ""
    phase: str = ""  # the token_usage `phase`, e.g. "director.reply"

    def metadata(self) -> dict[str, str | int]:
        return {"component": self.component, "version": self.version, "prompt_sha": self.prompt_sha,
                "phase": self.phase}
