"""Index the craft knowledge base: prose notes → `chunks` (corpus 'craft'), technique tables
(the cinematography terms database + camera_shots.csv, merged by `cine_terms.py`) → `craft_techniques`.
Derived state: the files in src/knowledge_base are the source of truth;
each run replaces the rows of every listed source and removes rows of sources no longer listed.

    python scripts/ingest_knowledge.py            # embeds when OPENAI__API_KEY is set
    python scripts/ingest_knowledge.py --dry-run  # show what would be indexed
    python scripts/ingest_knowledge.py --include-short-form  # also ad / social / video-format terms

Adapted from PromptMotion `scripts/vega_ingest_knowledge.py` + `ingest_craft_techniques.py`
(commit 1d748dc): same corpus choices and the effect-first technique text, OpenAI embeddings
at 1536 dimensions, and the doc_ingest chunker instead of a second one.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from collections import Counter

from _common import ROOT, Rest, load_env, vector
from cine_terms import LEGACY_SOURCE, load_terms

load_env()

from doc_ingest.engine.chunking import chunk  # noqa: E402
from doc_ingest.engine.extract import extract  # noqa: E402
from doc_ingest.runtime.config import get_config  # noqa: E402
from doc_ingest.runtime.llm import LLM  # noqa: E402

KB = ROOT / "src" / "knowledge_base"

# (path under src/knowledge_base, specialty). Only material that teaches CRAFT belongs here:
# architecture docs retrieve as noise and make agents worse than their static prompts.
PROSE: list[tuple[str, str]] = [
    *[(f"craft/{n}.md", n) for n in ("audience", "character", "cinematography", "dialogue",
                                     "directing", "editing", "producing", "sound")],
    ("craft/hiru-house-style.md", "house-style"),
    ("guides/veo-3-1-prompting-guide.md", "cinematography"),
    ("rules/camera_kinetics.md", "cinematography"),
    ("rules/physical_plausibility.md", "cinematography"),
    ("rules/character_consistency.md", "character"),
    ("rules/sceen_flow.md", "editing"),
    ("rules/pipeline_orchestration.md", "cinematography"),
]
# Technique tables are not chunked: one row per technique, columns verbatim (see cine_terms.py).
TERMS_DIR = KB / "cinematography"
LEGACY_CAMERA_CSV = KB / "techniques" / "camera_shots.csv"

EMBED_BATCH = 64


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


def embed_all(llm: LLM, texts: list[str]) -> list[list[float] | None]:
    if not llm.enabled:
        return [None] * len(texts)
    out: list[list[float] | None] = []
    for i in range(0, len(texts), EMBED_BATCH):
        out.extend(llm.embed(texts[i: i + EMBED_BATCH], phase="knowledge.embed"))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-short-form", action="store_true",
                        help="index the ad / social / video-format terms too (left out for Hiru's drama)")
    args = parser.parse_args()
    config = get_config()
    llm = LLM(config)
    model = config.embedding_model
    print(f"embeddings: {'ON (' + model + ')' if llm.enabled else 'OFF (no OPENAI__API_KEY): keyword search only'}")

    rows: list[dict] = []
    for rel, specialty in PROSE:
        raw = (KB / rel).read_text(encoding="utf-8")
        meta, body = strip_frontmatter(raw)
        title = meta.get("title") or rel
        source = f"knowledge_base/{rel}"
        for c in chunk(extract(body.encode(), rel, "text/markdown"), script_like=False):
            header = f"{title} — {c.heading}" if c.heading else title
            text = f"{header}\n\n{c.content}"
            rows.append({"corpus": "craft", "source": source, "ord": c.ord, "heading": c.heading,
                         "context_header": header, "content": c.content,
                         "content_hash": hashlib.sha256(f"{model}\n{text}".encode()).hexdigest(),
                         "meta": {"specialty": specialty, "title": title}, "_text": text})
        print(f"  {source}: {sum(1 for r in rows if r['source'] == source)} chunks ({specialty})")

    techniques = load_terms(TERMS_DIR, LEGACY_CAMERA_CSV, include_short_form=args.include_short_form)
    print(f"  {len(techniques)} techniques ({sum(t['source'] == LEGACY_SOURCE for t in techniques)} only in "
          f"camera_shots.csv); by domain: {dict(sorted(Counter(t['domain'] for t in techniques).items()))}")

    if args.dry_run:
        return

    db = Rest()
    # Reuse embeddings already stored for identical text with the same model.
    existing = {r["content_hash"]: r["embedding"] for r in db.get(
        "chunks", corpus="eq.craft", embedding="not.is.null", select="content_hash,embedding")}
    todo = [r for r in rows if r["content_hash"] not in existing]
    fresh = embed_all(llm, [r["_text"] for r in todo])
    for r, vec in zip(todo, fresh, strict=True):
        r["embedding"], r["embedding_model"] = vector(vec), model if vec else ""
    for r in rows:
        if r["content_hash"] in existing:
            r["embedding"], r["embedding_model"] = existing[r["content_hash"]], model
        r.pop("_text")

    db.delete("chunks", corpus="eq.craft")  # also clears sources that are no longer listed
    for i in range(0, len(rows), 100):
        db.insert("chunks", rows[i: i + 100])
    for t, vec in zip(techniques, embed_all(llm, [t["effect_text"] for t in techniques]), strict=True):
        t["embedding"], t["embedding_model"] = vector(vec), model if vec else ""
    db.delete("craft_techniques", id="gte.0")
    for i in range(0, len(techniques), 100):
        db.insert("craft_techniques", techniques[i: i + 100])
    embedded_now = sum(1 for v in fresh if v is not None)
    print(f"indexed {len(rows)} craft chunks ({embedded_now} embedded now, "
          f"{len(rows) - len(todo)} reused) and {len(techniques)} techniques")
    if not os.environ.get("OPENAI__API_KEY"):
        print("re-run after setting OPENAI__API_KEY to add embeddings")


if __name__ == "__main__":
    main()
