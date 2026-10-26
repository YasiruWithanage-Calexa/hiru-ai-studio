"""Load the cinematography terms database into `craft_techniques` rows (no I/O beyond reading CSVs).

Source: src/knowledge_base/cinematography/*.csv (the 629-term reference database, see
src/knowledge_base/UPSTREAM.md). Merged with PromptMotion's `camera_shots.csv`: where both name the
same technique there is ONE row: the terms row's new fields, with the legacy `definition`,
`use_case`, `abbreviation` and `example_film` kept (those were written feeling-first for intent
matching and the retrieval eval is calibrated on them); legacy rows with no counterpart stay as
they were. A query for "dolly" must not spend two of its four palette slots on the same shot.

Pure on purpose, so tests can import it without `.env`, Supabase or OpenAI.
"""
from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path
from typing import Any

# PromptMotion made short, ad-led video. Hiru makes television drama: a palette that answers a
# scene's feeling with "hook the viewer in the first 3 seconds" is worse than none. Left in the
# CSVs, left out of the index unless asked for (`--include-short-form`).
SHORT_FORM_CATEGORIES = frozenset({"video_format", "ad_structure", "social_technique"})

LEGACY_SOURCE = "knowledge_base/techniques/camera_shots.csv"
TERMS_SOURCE = "knowledge_base/cinematography/cine_terms.csv"


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)]


def norm(name: str) -> str:
    """'Dolly Zoom' == 'dolly-zoom' == 'DollyZoom'."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _hash(*fields: object) -> str:
    return hashlib.sha256("|".join(str(f) for f in fields).encode()).hexdigest()


def effect_text(use_case: str, effect: str, description: str, name: str, category: str,
                aliases: str = "", tags: list[str] | None = None) -> str:
    """What is embedded and searched. Feeling first, mechanics second, label last: queries arrive
    as 'the viewer must feel she is powerless', not as camera vocabulary."""
    head = ". ".join(p.rstrip(".") for p in (use_case, effect, description) if p)
    label = f"{name}, {category}" + (f"; also called {aliases}" if aliases else "")
    return f"{head}. ({label})" + (f" Tags: {', '.join(tags)}." if tags else "")


def load_terms(directory: Path, legacy_csv: Path | None = None, *,
               include_short_form: bool = False) -> list[dict[str, Any]]:
    categories = {r["category_id"]: r for r in _read(directory / "categories.csv")}
    subcategories = {r["subcategory_id"]: r["subcategory_name"] for r in _read(directory / "subcategories.csv")}
    tag_names = {r["tag_id"]: r["tag_name"] for r in _read(directory / "tags.csv")}
    terms = _read(directory / "cine_terms.csv")
    names = {t["term_id"]: t["term_name"] for t in terms}

    tags: dict[str, list[str]] = {}
    for r in _read(directory / "term_tags.csv"):
        if r["term_id"] not in names or r["tag_id"] not in tag_names:
            raise ValueError(f"term_tags.csv: unknown term/tag in {r}")
        tags.setdefault(r["term_id"], []).append(tag_names[r["tag_id"]])
    related: dict[str, list[dict[str, str]]] = {}
    for r in _read(directory / "term_relations.csv"):
        if r["term_id"] not in names or r["related_term_id"] not in names:
            raise ValueError(f"term_relations.csv: unknown term in {r}")
        related.setdefault(r["term_id"], []).append(
            {"type": r["relation_type"], "name": names[r["related_term_id"]]})

    legacy_rows = [r for r in _read(legacy_csv) if r.get("shot_name")] if legacy_csv else []
    # Legacy shot names are sometimes 'A / B' (two names for one thing): every part matches.
    legacy_by_key: dict[str, dict[str, str]] = {}
    for r in legacy_rows:
        for part in r["shot_name"].split("/"):
            legacy_by_key.setdefault(norm(part), r)
    claimed: set[str] = set()

    rows: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    for t in terms:
        cat = categories.get(t["category_id"])
        if cat is None or not t["term_name"] or not t["term_slug"]:
            raise ValueError(f"cine_terms.csv: bad row {t}")
        if t["term_slug"] in seen_slugs:
            raise ValueError(f"cine_terms.csv: duplicate slug {t['term_slug']}")
        seen_slugs.add(t["term_slug"])
        if cat["category_slug"] in SHORT_FORM_CATEGORIES and not include_short_form:
            continue
        keys = {norm(t["term_name"]), *(norm(a) for a in t["aliases"].split(",") if a.strip())}
        legacy = next((legacy_by_key[k] for k in keys if k in legacy_by_key
                       and legacy_by_key[k]["shot_name"] not in claimed), None)
        if legacy:
            claimed.add(legacy["shot_name"])
        term_tags = tags.get(t["term_id"], [])
        leg = legacy or {}
        definition = leg.get("definition") or t["description"]
        use_case = leg.get("use_case") or t["use_case"]
        fields = {
            "domain": cat["domain"], "category": cat["category_name"], "name": t["term_name"],
            "abbreviation": leg.get("abbreviation", ""), "definition": definition, "use_case": use_case,
            "example_film": leg.get("example_film", ""),
            "slug": t["term_slug"],
            "subcategory": subcategories.get(t["subcategory_id"], ""),
            "effect": t["effect"], "example_scene": t["example_scene"],
            "prompt_phrase": t["prompt_phrase"], "aliases": t["aliases"],
            "complexity": t["complexity"], "ai_supported": t["is_ai_supported"] == "1",
            "tags": term_tags, "related": related.get(t["term_id"], []),
        }
        rows.append({**fields, "source": TERMS_SOURCE,
                     "effect_text": effect_text(use_case, t["effect"], definition, t["term_name"],
                                                cat["category_name"], t["aliases"], term_tags),
                     "row_hash": _hash(*fields.values(), repr(fields["tags"]), repr(fields["related"]))})

    for r in legacy_rows:
        if r["shot_name"] in claimed:
            continue
        use_case, definition = r.get("use_case", "").rstrip("."), r.get("definition", "").rstrip(".")
        rows.append({
            # Same keys as a terms row: a PostgREST bulk insert needs every object to match.
            "slug": "", "subcategory": "", "effect": "", "example_scene": "", "prompt_phrase": "",
            "aliases": "", "complexity": "", "ai_supported": True, "tags": [], "related": [],
            "domain": "camera", "category": r["category"], "name": r["shot_name"],
            "abbreviation": r.get("abbreviation", ""), "definition": r.get("definition", ""),
            "use_case": r.get("use_case", ""), "example_film": r.get("example_film", ""),
            "effect_text": ". ".join(p for p in (use_case, definition) if p)
                           + f". ({r['shot_name']}, {r['category']})",
            "source": LEGACY_SOURCE,
            "row_hash": _hash(*(r.get(k, "") for k in
                                ("category", "shot_name", "abbreviation", "definition", "use_case", "example_film")))})
    return rows
