"""The cinematography knowledge base: technique rows from the CSV tables (see terms.py for the merge)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from hiru_ai.core.manifest import KnowledgeBaseManifest
from hiru_ai.knowledge_bases.cinematography.terms import load_terms
from hiru_ai.rag.knowledge import Item, KnowledgeBase


class Cinematography(KnowledgeBase):
    def technique_items(self, **options: Any) -> list[Item]:
        rows = load_terms(self.sources, self.sources / "camera_shots.csv",
                          include_short_form=bool(options.get("include_short_form")))
        return [Item(r, r["effect_text"]) for r in rows]


def build(manifest: KnowledgeBaseManifest, folder: Path) -> KnowledgeBase:
    return Cinematography(manifest, folder)
