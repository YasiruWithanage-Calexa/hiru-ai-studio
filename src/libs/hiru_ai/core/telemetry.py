"""Logging and trace tags. Tags name the part, its version and its prompt, so a run can be traced to what ran.

Which tracing tool receives them is still open (ADR 0008); until then they travel as LangChain run metadata
and appear in logs. Never put prompts, scripts or keys in a tag.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass


def logger(name: str) -> logging.Logger:
    return logging.getLogger(f"hiru_ai.{name}")


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
