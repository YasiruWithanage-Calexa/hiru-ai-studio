"""Turn a tool's plain function into a LangChain tool that reads its dependencies from the run.

A tool is `run(args, ctx) -> Result`: typed arguments in, a pydantic result out, the scope and the ports from
`RunContext`. That function is what the CLI, the tests and a system call directly. `from_part` wraps it for an
agent's tool loop (`ToolRuntime.context` is the same `RunContext`, injected by LangGraph, so a model can neither
see nor choose the production, the actor, the scene in scope or the ports).

What every tool gets once, here, instead of in each tool (plan/2026-11-04 §4 "the tool contract"):

  * the description a model reads is the manifest's `summary` + `guide`
  * `response_format` ("concise" by default) and paging (`page`, `page_size`, `next_page`, `total`) come from the
    `ToolArgs` / `Paged` bases and `page()`
  * a result is cut to the manifest's `max_result_tokens`, with a hint naming the argument that narrows it
  * a refused call answers `{"error", "how_to_fix", "example"}`; a failed port answers a clear error, never a crash
  * one telemetry event per call (`RunContext.tool_events`: tool id, ms, result tokens, error)
"""
from __future__ import annotations

import copy
import difflib
import json
import re
import time
from collections.abc import Callable, Iterable, Sequence
from typing import Any, ClassVar, Literal, TypeVar
from uuid import UUID

from langchain.tools import ToolRuntime
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from contracts.canon import name_key
from hiru_ai.core import parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import HiruAIError, ToolRefused
from hiru_ai.core.ports import Row, SceneStore
from hiru_ai.core.telemetry import ToolEvent, log_tool_event, logger, tool_span
from hiru_ai.core.tokens import tokens_of

_log = logger("tooling")
T = TypeVar("T")

Format = Literal["concise", "detailed"]
PAGE_SIZE_MAX = 30


# ── what every read tool's arguments share ───────────────────────────────────────────────────────────────────────────


class ToolArgs(BaseModel):
    """Base of a read tool's arguments. `NARROW_WITH` names what a model can pass to get a smaller answer (the hint
    added when a result is cut); without it the hint is built from the argument names."""

    NARROW_WITH: ClassVar[str] = ""

    response_format: Format = Field(
        "concise", description="'concise' (default) is the short answer; 'detailed' adds every field. "
                               "Ask for 'detailed' only when the concise answer lacks what you need.")


class Paged(ToolArgs):
    """A tool that lists things: `page` from 1, `page_size` up to 30; the result says `next_page` and `total`."""

    page: int = Field(1, ge=1, description="Page number, from 1")
    page_size: int = Field(10, ge=1, le=PAGE_SIZE_MAX, description="Items per page (at most 30)")


def page[T](items: Sequence[T], number: int, size: int) -> tuple[list[T], dict[str, int | None]]:
    """-> (this page, `{"total", "page", "page_size", "next_page"}`); `next_page` is None on the last."""
    size = max(1, min(size, PAGE_SIZE_MAX))
    start = (max(1, number) - 1) * size
    chosen = list(items[start:start + size])
    more = start + size < len(items)
    return chosen, {"total": len(items), "page": max(1, number), "page_size": size,
                    "next_page": max(1, number) + 1 if more else None}


__all__ = ["tokens_of"]  # re-exported: `tooling.tokens_of` is where the tools and tests look


# ── size of a result ─────────────────────────────────────────────────────────────────────────────────────────────────


def dumps(data: Any) -> str:
    """JSON with the script's own characters: a spoken line goes out byte for byte (never `\\u` escapes)."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)


def _lists(node: Any, path: tuple[Any, ...] = ()) -> Iterable[tuple[tuple[Any, ...], list[Any]]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _lists(value, (*path, key))
    elif isinstance(node, list):
        yield path, node
        for n, value in enumerate(node):
            yield from _lists(value, (*path, n))


def _at(data: Any, path: tuple[Any, ...]) -> Any:
    for step in path:
        data = data[step]
    return data


def _strings(node: Any, path: tuple[Any, ...] = ()) -> Iterable[tuple[tuple[Any, ...], str]]:
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, (*path, key))
    elif isinstance(node, list):
        for n, value in enumerate(node):
            yield from _strings(value, (*path, n))


def fit(data: dict[str, Any], limit: int, hint: str) -> tuple[dict[str, Any], bool]:
    """`data` cut to about `limit` tokens: the biggest list loses its tail, then the longest text is shortened. The
    result says what it shows and what to pass to get the rest. -> (result, was it cut)."""
    if tokens_of(dumps(data)) <= limit:
        return data, False
    work = copy.deepcopy(data)
    shown: dict[str, str] = {}
    for _ in range(40):
        current = tokens_of(dumps({**work, "truncated": {"shown": shown, "hint": hint}}))
        if current <= limit:
            break
        lists = [(p, v) for p, v in _lists(work) if len(v) > 1]
        if lists:
            path, items = max(lists, key=lambda pv: len(dumps(pv[1])))
            keep = max(1, min(len(items) - 1, int(len(items) * limit / current * 0.9)))
            label = ".".join(str(s) for s in path) or "items"
            was = int(shown[label].split(" of ")[1]) if label in shown else len(items)
            shown[label] = f"{keep} of {was}"
            del items[keep:]
            continue
        texts = [(p, s) for p, s in _strings(work) if len(s) > 200]
        if not texts:
            break
        path, text = max(texts, key=lambda ps: len(ps[1]))
        parent = _at(work, path[:-1]) if path else work
        parent[path[-1]] = text[: max(100, len(text) // 2)].rstrip() + " …"
    return {**work, "truncated": {"shown": shown, "hint": hint}}, True


def narrow_hint(args: type[BaseModel]) -> str:
    """What to tell a model that got a cut result: the argument that narrows it."""
    fixed = getattr(args, "NARROW_WITH", "")
    if fixed:
        return str(fixed)
    fields = args.model_fields
    options = [f"a smaller `{n}`" for n in ("page_size",) if n in fields]
    options += [f"`{n}`" for n in ("include", "shots", "shot", "kind", "query", "episode", "scene") if n in fields]
    options += ["`response_format: concise`"] if "response_format" in fields else []
    return "Ask for less: " + (", ".join(options) or "a narrower request") + "."


# ── names a model gets wrong ─────────────────────────────────────────────────────────────────────────────────────────


def closest(name: str, candidates: Iterable[str], n: int = 3) -> list[str]:
    """The `n` candidates nearest to `name` (a name or a code), nearest first: a typo, a nickname, half a name."""
    key = name_key(name)
    names = {name_key(c): c for c in candidates if name_key(c)}
    contained = [names[k] for k in names if key and (key in k or k in key)]
    near = [names[k] for k in difflib.get_close_matches(key, list(names), n=n, cutoff=0.4)]
    return list(dict.fromkeys([*contained, *near]))[:n]


def not_found(kind: str, name: str, candidates: Iterable[str], *, example: str = "", where: str = "") -> ToolRefused:
    """A "not found" that helps: the 3 closest names, and how to list the rest."""
    near = closest(name, candidates)
    how = (f"Did you mean {', '.join(repr(c) for c in near)}?" if near else
           f"Nothing is close to it. List the {kind}s first.") + (f" {where}" if where else "")
    return ToolRefused(f"there is no {kind} called {name!r}", how_to_fix=how, example=example)


def shot_code(number: int) -> str:
    """Shot 4 → "S04": what a model reads and writes for a shot, never an id."""
    return f"S{int(number):02d}"


def shot_number(value: str | int, *, example: str = "S03") -> int:
    """"S03", "s3", "3" or 3 → 3."""
    match = re.fullmatch(r"\s*[Ss]?\s*(\d{1,3})\s*", str(value))
    if match is None:
        raise ToolRefused(f"{value!r} is not a shot", how_to_fix="Name a shot by its number, like S03 or 3.",
                          example=example)
    return int(match.group(1))


def scene_label(scene: Row) -> str:
    """The scene as a person says it: "E1S2" (episode 1, scene 2)."""
    number = (scene.get("episode") or {}).get("number")
    return f"E{number}S{scene.get('number')}" if number is not None else f"S{scene.get('number')}"


# ── scope ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def production_of(ctx: RunContext) -> UUID:
    """The production this run works on. It comes from the trusted payload, never from a model's arguments."""
    if ctx.production_id is None:
        raise ToolRefused("this run is not scoped to a production")
    return ctx.production_id


def scene_of(ctx: RunContext, scene_id: str) -> tuple[SceneStore, Row]:
    """The scene store and the scene, only when the scene belongs to this run's production."""
    store: SceneStore = ctx.need("scenes", "SceneStore")
    rows = store.scenes(production_of(ctx), [str(scene_id)])
    if not rows:
        raise ToolRefused(f"there is no scene {scene_id} in this production")
    return store, rows[0]


_SCENE_REF = re.compile(r"^\s*(?:[Ee]\s*(\d+)\s*[.\-\s]?\s*)?[Ss]?\s*(\d+)\s*$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def parse_scene_ref(text: str) -> tuple[int | None, int] | None:
    """"E1S2" / "1.2" -> (1, 2); "2" -> (None, 2); anything else -> None. No episode named: None in its place."""
    match = _SCENE_REF.match(text)
    if match is None:
        return None
    return (int(match.group(1)) if match.group(1) else None), int(match.group(2))


def scene_in_scope(ctx: RunContext, ref: str | None = None) -> tuple[SceneStore, Row]:
    """The scene a call is about: `ref` ("E1S2", "2" = scene 2 of the scene in scope's episode, or an id a system
    passes) or, with none, the scene in scope for the run (`RunContext.scene_id`). Always inside this production."""
    store: SceneStore = ctx.need("scenes", "SceneStore")
    text = (ref or "").strip()
    if not text:
        if ctx.scene_id is None:
            raise ToolRefused("this run has no scene in scope", how_to_fix="Name the scene, like E1S2.",
                              example='{"scene": "E1S2"}')
        return scene_of(ctx, str(ctx.scene_id))
    if _UUID.match(text):
        return scene_of(ctx, text)
    parsed = parse_scene_ref(text)
    if parsed is None:
        raise ToolRefused(f"{text!r} is not a scene", how_to_fix="Name a scene like E1S2 (episode 1, scene 2) or 2.",
                          example='{"scene": "E1S2"}')
    rows = store.scenes(production_of(ctx), None)
    episode, number = parsed
    if episode is None and ctx.scene_id is not None:
        here = next((r for r in rows if str(r["id"]) == str(ctx.scene_id)), None)
        episode = (here.get("episode") or {}).get("number") if here else None
    found = [r for r in rows if int(r.get("number") or -1) == number
             and (episode is None or (r.get("episode") or {}).get("number") == episode)]
    if not found:
        raise not_found("scene", text, [scene_label(r) for r in rows], example='{"scene": "E1S2"}')
    return store, found[0]


# ── the LangChain form ───────────────────────────────────────────────────────────────────────────────────────────────


def description(summary: str, guide: str) -> str:
    """What a model reads about the tool: the one-line summary, then the guide (when to use it and when not to)."""
    return summary if not guide.strip() else f"{summary}\n\n{guide.strip()}"


def cited(data: dict[str, Any]) -> list[dict[str, str]]:
    """The passages a search tool's answer carries, as the `{chunk_id, label}` a reply cites (`memory_search` rows
    have a `cite`, `search_kb` passages a `cite` and a `source`)."""
    out = []
    for key, default in (("memories", "production memory"), ("passages", "")):
        for row in data.get(key) or []:
            if isinstance(row, dict) and row.get("cite"):
                out.append({"chunk_id": str(row["cite"]), "label": str(row.get("source") or default)})
    return out


def from_part(package: str, args: type[BaseModel], run: Callable[[Any, RunContext], BaseModel]) -> StructuredTool:
    """`package` is the tool's dotted path (`__package__`); its id, description and result budget come from its
    manifest."""
    ident = package.rsplit(".", 1)[-1]
    manifest = parts._registry().get("tool", ident).manifest
    limit = int(getattr(manifest, "max_result_tokens", 1500))
    hint = narrow_hint(args)

    def call(runtime: ToolRuntime, **kwargs: Any) -> str:
        ctx = runtime.context
        if not isinstance(ctx, RunContext):
            raise ToolRefused("this tool runs inside a graph built with a RunContext")
        started, error, cut = time.perf_counter(), "", False
        with tool_span(ident, int(manifest.version), str(getattr(manifest, "effect", "read"))) as span:
            try:
                data = run(args.model_validate(kwargs), ctx).model_dump(mode="json")
                ctx.citations.extend(cited(data))
                data, cut = fit(data, limit, hint)
                text = dumps(data)
            except ToolRefused as exc:
                error, text = "refused", dumps(exc.as_result())
            except HiruAIError as exc:  # a missing port, a model that is off: say so; the agent goes on without it
                error = type(exc).__name__
                _log.warning("tool %s failed: %s", ident, exc)
                text = dumps({"error": "That lookup is not available right now.",
                              "how_to_fix": "Answer without it, or say what you could not check."})
            except Exception:
                error = "failed"
                _log.warning("tool %s failed", ident, exc_info=True)
                text = dumps({"error": "That lookup is not available right now.",
                              "how_to_fix": "Answer without it, or say what you could not check."})
            event = ToolEvent(tool=ident, ms=round((time.perf_counter() - started) * 1000, 1),
                              result_tokens=tokens_of(text), error=error, truncated=cut)
            span(event)
        ctx.tool_events.append(event)
        log_tool_event(event)
        return text

    return StructuredTool.from_function(func=call, name=ident, description=description(manifest.summary, getattr(
        manifest, "guide", "")), args_schema=args)
