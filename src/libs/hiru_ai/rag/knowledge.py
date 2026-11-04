"""The base every knowledge base builds on: read its sources, make rows, embed what is new, replace its rows.

A knowledge base is derived state: the files in its `sources/` folder are the truth, and an ingest replaces the rows
under the base's `source_prefix` as a set (so removing a file removes its chunks). Several bases share the `craft`
corpus (craft, guides, rules), which is why rows are replaced by source prefix and not by corpus.

Chunking is the `chunk` step and text extraction the `extract_text` step, reached by id (`core.parts`, ADR 0009): one
chunker for uploaded documents and for the craft corpus. Nothing here writes to a database; the store is the
`KnowledgeStore` port, so a test runs an ingest on a fake.
"""
from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hiru_ai.core import parts
from hiru_ai.core.errors import ManifestError
from hiru_ai.core.manifest import KnowledgeBaseManifest
from hiru_ai.core.ports import KnowledgeStore

Row = dict[str, Any]
Embed = Callable[[list[str]], list[list[float] | None]]  # texts → one vector (or None) per text, in order


@dataclass(frozen=True)
class Item:
    """A row to store and the text that is embedded for it."""

    row: Row
    text: str


@dataclass
class Report:
    kb: str
    chunks: int = 0
    techniques: int = 0
    embedded: int = 0  # embedded by this run
    reused: int = 0  # embeddings kept because the text and model are unchanged
    by_source: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    dry_run: bool = False


def strip_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    meta = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip("\"'")
    return meta, text[end + 4:]


def content_hash(model: str, text: str) -> str:
    """Identifies a chunk's text AND the embedding model, so a model change re-embeds and nothing else does."""
    return hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()


class KnowledgeBase:
    """Behaviour comes from the manifest; a base overrides `items` or `technique_items` when its sources need it."""

    def __init__(self, manifest: KnowledgeBaseManifest, folder: Path) -> None:
        self.manifest, self.folder = manifest, folder

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def sources(self) -> Path:
        return self.folder / self.manifest.sources

    # ── what a base builds (pure: files in, rows out) ─────────────────────────────────────

    def items(self, model: str) -> list[Item]:
        """Chunk rows (`chunks` table) with the text to embed for each. Files listed in the manifest, as prose."""
        out: list[Item] = []
        extract = parts.step("extract_text", "step").run
        chunker = parts.step("chunk", "step").run
        script_like = bool(self.manifest.chunking.get("script_like", False))
        prefix = self.manifest.source_prefix
        for f in self.manifest.files:
            rel = f"{prefix.removeprefix('knowledge_base/')}{f.path}"  # the path the corpus has always cited
            meta, body = strip_frontmatter((self.sources / f.path).read_text(encoding="utf-8"))
            title = meta.get("title") or rel
            extracted = extract({"filename": rel, "mime_type": "text/markdown",
                                 "data_b64": base64.b64encode(body.encode()).decode()})
            if "rejected" in extracted:
                raise ManifestError(f"knowledge base {self.id}: {f.path} was refused: {extracted['rejected']}")
            for c in chunker({"kind": extracted["kind"], "lines": extracted["lines"],
                              "script_like": script_like})["chunks"]:
                header = f"{title} — {c['heading']}" if c["heading"] else title
                text = f"{header}\n\n{c['content']}"
                out.append(Item({
                    "corpus": self.manifest.corpus, "source": f"{prefix}{f.path}", "ord": c["ord"],
                    "heading": c["heading"], "context_header": header, "content": c["content"],
                    "content_hash": content_hash(model, text), "meta": {**f.meta, "title": title}}, text))
        return out

    def technique_items(self, **options: Any) -> list[Item]:
        """Rows of the `craft_techniques` table, with the text to embed. Only a technique base has any."""
        return []

    # ── ingest ────────────────────────────────────────────────────────────────────────────

    def ingest(self, store: KnowledgeStore, embed: Embed, model: str, *, dry_run: bool = False,
               **options: Any) -> Report:
        report = Report(self.id, dry_run=dry_run)
        chunks = self.items(model) if self.manifest.store == "chunks" else []
        techniques = self.technique_items(**options) if self.manifest.store == "techniques" else []
        report.chunks, report.techniques = len(chunks), len(techniques)
        for item in chunks:
            report.by_source[item.row["source"]] = report.by_source.get(item.row["source"], 0) + 1
        if dry_run:
            return report

        if self.manifest.store == "chunks":  # even with no chunks left: removing a file removes its rows
            prefix, corpus = self.manifest.source_prefix, self.manifest.corpus
            existing = store.embeddings(corpus, prefix)
            fresh = [i for i in chunks if i.row["content_hash"] not in existing]
            vectors = dict(zip((i.row["content_hash"] for i in fresh), embed([i.text for i in fresh]), strict=True))
            rows = []
            for item in chunks:
                h = item.row["content_hash"]
                if h in existing:
                    rows.append({**item.row, "embedding": existing[h], "embedding_model": model})
                else:
                    rows.append({**item.row, "embedding": vectors[h], "embedding_model": model if vectors[h] else ""})
            report.embedded = sum(1 for h in vectors if vectors[h] is not None)
            report.reused = len(chunks) - len(fresh)
            store.replace_chunks(corpus, prefix, rows)
        if self.manifest.store == "techniques":
            if not techniques:
                raise ManifestError(f"knowledge base {self.id} loaded no techniques; refusing to empty the table")
            vectors_t = embed([i.text for i in techniques])
            store.replace_techniques([{**i.row, "embedding": v, "embedding_model": model if v else ""}
                                      for i, v in zip(techniques, vectors_t, strict=True)])
            report.embedded += sum(1 for v in vectors_t if v is not None)
        return report


def load(ident: str, registry: Any = None) -> KnowledgeBase:
    """The knowledge base with this id, built by its own `ingest.py`."""
    from hiru_ai.core.registry import Registry

    registry = registry or parts._registry()
    comp = registry.get("knowledge_base", ident)
    m = comp.manifest
    if not isinstance(m, KnowledgeBaseManifest):  # pragma: no cover - the registry keys by kind
        raise ManifestError(f"{ident} is not a knowledge base")
    if m.ingest not in ("files", "tables"):
        raise ManifestError(f"knowledge base {ident} is not ingested from files here ({m.ingest}); "
                            + ("the doc_ingest job fills it" if m.ingest == "upload"
                               else f"{m.fed_by} fills it"))
    assert isinstance(registry, Registry)
    build = registry.resolve("knowledge_base", ident, m.entry)
    kb = build(m, comp.folder)
    assert isinstance(kb, KnowledgeBase)
    return kb
