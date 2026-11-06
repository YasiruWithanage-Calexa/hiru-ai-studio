"""`production_memory`: the production's own direction, added to the agent's user message (plan/2026-11-05d M5).

An agent subscribes with two lines in its manifest:

    middleware: [static_first, usage, absent_safe, production_memory]
    memory: [camera, lighting, visual]       # the topics it is given; `*` for all

For each call the middleware takes the production's entries (`draft` and `approved`, never `rejected`; read once per
run), keeps the subscribed topics, every `fact` and every `must` (a rule binds everyone), narrows `place:`,
`character:` and
`episode:` entries to the ones the call is about when the agent's `memory_scope(inp)` hook says which, and appends them
to the END of the user message as a tagged block, so the cached system prefix is unchanged. No entries, no block: the
call is byte for byte what it was before the memory existed.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from contracts.memory import parse_target
from hiru_ai.core import memory
from hiru_ai.core.context import RunContext
from hiru_ai.core.middleware.base import ModelCall, Next
from hiru_ai.core.middleware.untrusted_text import defuse

name = "production_memory"
MAX_ENTRIES = 40  # per call: `must` first, then the narrowest scope
ALL_TOPICS = "*"
NOTE = ("The production's own direction, from its documents. Follow it unless it breaks a rule you were given; say so "
        "when it does. Drafts are not yet approved by a person.")
_CANON = "canon"
_NARROW = {"place": 0, "character": 0, "episode": 0, "when": 1, "production": 2}  # smaller = narrower


def _canon(ctx: RunContext) -> list[dict[str, Any]]:
    """The production's canon entities (names and aliases), read once per run; none when it cannot be read."""
    if _CANON not in ctx.memory_cache:
        found: list[dict[str, Any]] = []
        port = ctx.ports.canon
        if port is not None and ctx.production_id is not None:
            try:
                found = [e for e in port.entities(ctx.production_id)]
            except Exception:
                found = []
        ctx.memory_cache[_CANON] = found
    cached: list[dict[str, Any]] = ctx.memory_cache[_CANON]
    return cached


def _same(target: str, other: str, canon: list[dict[str, Any]], kind: str) -> bool:
    """Do two names mean the same entity? Both are matched to the canon first, so an alias counts; when either is
    not in the canon (not yet built) the two names are compared as they are, by the same rule."""
    from hiru_ai.core import parts  # lazy: the registry imports this package

    analyse = parts.step("structure_analyse")
    match = analyse.match_location if kind == "location" else analyse.match_speaker
    cards = [e for e in canon if str(e.get("kind")) == kind]
    a, b = match(target, cards)[0], match(other, cards)[0]
    if a is not None and b is not None:
        return str(a.get("id")) == str(b.get("id"))
    return bool(match(target, [{"name": other, "aliases": []}])[0] is not None)


def about(entry: dict[str, Any], scope: Mapping[str, Any] | None, ctx: RunContext) -> bool:
    """Does this entry concern the call? Only `place:`, `character:` and `episode:` entries are narrowed, and only on
    what the agent's hook says: a scope with no place, nobody, or no episode leaves those entries in."""
    target = parse_target(str(entry.get("applies_to") or ""))
    if target is None or not scope:
        return True
    kind, value = target
    if kind == "place":
        place = str(scope.get("place") or "")
        return not place or _same(value, place, _canon(ctx), "location")
    if kind == "character":
        people = [str(p) for p in scope.get("people") or []]
        return not people or any(_same(value, p, _canon(ctx), "character") for p in people)
    if kind == "episode":
        episode = scope.get("episode")
        return episode is None or int(value) == int(episode)
    return True


def select(rows: list[dict[str, Any]], topics: tuple[str, ...], scope: Mapping[str, Any] | None,
           ctx: RunContext) -> list[dict[str, Any]]:
    """The entries one call is given, in the order the documents gave them (`rows` order)."""
    every = ALL_TOPICS in topics
    said: set[tuple[str, str, str]] = set()
    chosen = []
    for r in rows:
        if not ((every or r.get("topic") in topics or r.get("strength") in ("fact", "must")) and about(r, scope, ctx)):
            continue
        if (k := memory.key(r)) not in said:  # the same direction from two documents is said once
            said.add(k)
            chosen.append(r)
    if len(chosen) <= MAX_ENTRIES:
        return chosen

    def rank(n: int) -> tuple[int, int, int]:
        row = chosen[n]
        kind = (parse_target(str(row.get("applies_to") or "")) or ("production", ""))[0]
        return (row.get("strength") != "must", _NARROW[kind], n)

    keep = sorted(range(len(chosen)), key=rank)[:MAX_ENTRIES]
    return [chosen[n] for n in sorted(keep)]


def line(row: dict[str, Any]) -> str:
    target = parse_target(str(row.get("applies_to") or "")) or ("production", "")
    tags = [str(row["strength"])] if row.get("strength") in ("must", "fact") else []
    tags.append(str(row.get("topic") or ""))
    if target[0] != "production":
        tags.append(f"{target[0]}: {target[1]}")
    draft = " (draft)" if row.get("status") != "approved" else ""
    return f"- [{' · '.join(t for t in tags if t)}] {' '.join(str(row.get('says') or '').split())}{draft}"


def block(rows: list[dict[str, Any]]) -> str:
    """The entries as the tagged block the agent reads. A closing tag inside an entry is defused like a document's."""
    body = defuse("\n".join(line(r) for r in rows)).replace("</production_memory", "<\\/production_memory")
    return f'<production_memory note="{NOTE}">\n{body}\n</production_memory>'


class ProductionMemory:
    name = name

    def __call__(self, call: ModelCall, ctx: RunContext, nxt: Next) -> Any:
        if call.memory_topics:
            rows = memory.entries(ctx)
            chosen = select(rows, call.memory_topics, call.memory_scope, ctx) if rows else []
            if chosen:
                text = block(chosen)
                call.user = f"{call.user}\n\n{text}" if call.user else text
        return nxt(call)
