"""From the knowledge bases an agent lists to the corpora a search may read.

An agent's manifest says `knowledge: [craft, rules]`; this turns those ids into the corpora of the run, so the agent
can search exactly those and nothing else. The ids come from the manifest (code review), never from a model. When the
caller already narrowed the run (`RunContext.corpora`, from trusted data), the agent gets the overlap only: a manifest
can reduce what a run may read, never widen it.

It lives in `core` because the agent builder applies it (an agent may only search the bases it lists).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from hiru_ai.core import parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.manifest import KnowledgeBaseManifest
from hiru_ai.core.registry import Registry


def corpora_of(kb_ids: Iterable[str], registry: Registry | None = None) -> tuple[str, ...]:
    """The `chunks` corpora behind these knowledge bases, in the order listed, each once.

    A base that fills the technique table has no chunk corpus (agents reach it through the `technique_lookup` tool).
    """
    registry = registry or parts._registry()
    out: list[str] = []
    for ident in kb_ids:
        m = registry.get("knowledge_base", ident).manifest
        assert isinstance(m, KnowledgeBaseManifest)
        if m.store == "chunks" and m.corpus not in out:
            out.append(m.corpus)
    return tuple(out)


def scope_for(ctx: RunContext, kb_ids: Iterable[str], registry: Registry | None = None) -> RunContext:
    """The run as the agent sees it: `search_kb` reads only the corpora of the agent's knowledge bases."""
    mine = corpora_of(kb_ids, registry)
    allowed = tuple(c for c in mine if c in ctx.corpora) if ctx.corpora else mine
    return replace(ctx, corpora=allowed)
