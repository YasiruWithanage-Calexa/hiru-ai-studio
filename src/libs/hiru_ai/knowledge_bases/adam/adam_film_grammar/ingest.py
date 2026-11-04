"""The adam_film_grammar knowledge base. All behaviour comes from component.yaml; the shared base does the work."""
from __future__ import annotations

from pathlib import Path

from hiru_ai.core.manifest import KnowledgeBaseManifest
from hiru_ai.rag.knowledge import KnowledgeBase


def build(manifest: KnowledgeBaseManifest, folder: Path) -> KnowledgeBase:
    return KnowledgeBase(manifest, folder)
