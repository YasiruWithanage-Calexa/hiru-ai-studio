"""The code half of the canon models: what the extractor's answer becomes, how it joins the rules' canon, and which
duplicates the deduper's groups remove. Ported from `canon_extract/engine/model.py`. Merges are applied by code, never
by the model: a group the list does not contain is ignored, and two coded entries are two entities whatever the model
thinks."""
from __future__ import annotations

from typing import Any

from contracts.canon import CODE_PREFIX, CanonKind, name_key
from hiru_ai.core import parts

Candidate = dict[str, Any]
CARD_FIELDS = ("summary", "age", "gender", "appearance", "wardrobe", "voice", "accent", "look", "details", "notes")
# Fields the documents usually state outright ("Voice: ...", "Wardrobe anchor: ..."): a value the rules found there is
# the author's wording and is kept over the model's paraphrase.
LABELLED = ("wardrobe", "voice", "accent")


def _rules() -> Any:
    return parts.step("canon_rules")


def counts(cands: list[Candidate]) -> dict[str, list[dict[str, Any]]]:
    """Who speaks and where scenes are set, by the scripts: what the extractor is told about them."""
    return {"speakers": [{"name": c["name"], "count": c["lines"]} for c in cands if c["kind"] == CanonKind.CHARACTER],
            "places": [{"name": c["name"], "count": c["scenes"]} for c in cands if c["kind"] == CanonKind.LOCATION]}


def from_answer(entities: list[dict[str, Any]]) -> list[Candidate]:
    rules = _rules()
    out: list[Candidate] = []
    for e in entities:
        name = rules.display_name(str(e.get("name", "")))
        if not name:
            continue
        kind = CanonKind(e["kind"])
        code = str(e.get("code") or "").strip().upper()
        card = {k: " ".join(str(v).split()) for k, v in (e.get("card") or {}).items() if k in CARD_FIELDS and v}
        out.append(rules.candidate(kind, name, code=code if code[:1] == CODE_PREFIX[kind] else "",
                                   aliases=[str(a) for a in e.get("aliases", []) if a],
                                   core=bool(e.get("core")), card=card, source="model"))
    return out


def combine(rule_cands: list[Candidate], model_cands: list[Candidate]) -> list[Candidate]:
    """The rules' entities and codes stay; the model's card values win except labelled ones."""
    rules = _rules()
    merged = rules.merge(rule_cands)
    for m in model_cands:
        match = next((c for c in merged if rules.same(c, m)), None)
        if match is None:
            merged.append(m)
            continue
        for k, v in m["card"].items():
            if v and not (k in LABELLED and match["card"].get(k)):
                match["card"][k] = v
        for alias in m["aliases"]:
            if name_key(alias) not in {name_key(match["name"]), *map(name_key, match["aliases"])}:
                match["aliases"].append(alias)
        match["core"] = match["core"] or m["core"]
        match["code"] = match["code"] or m["code"]
    return merged


def dedupe_input(cands: list[Candidate]) -> list[dict[str, Any]]:
    return [{"kind": c["kind"].value if isinstance(c["kind"], CanonKind) else c["kind"], "name": c["name"],
             "code": c["code"], "aliases": list(c["aliases"]), "summary": c["card"].get("summary") or ""}
            for c in cands]


def apply_groups(cands: list[Candidate], groups: list[dict[str, Any]]) -> list[Candidate]:
    rules = _rules()
    by_name = {(c["kind"], name_key(c["name"])): c for c in cands}
    dropped: set[int] = set()
    for g in groups:
        keep = by_name.get((g["kind"], name_key(g["keep"])))
        if keep is None:
            continue
        for other_name in g.get("same_as_keep", []):
            other = by_name.get((g["kind"], name_key(other_name)))
            if other is None or other is keep or id(other) in dropped:
                continue
            if keep["code"] and other["code"] and keep["code"] != other["code"]:
                continue  # two coded entries are two entities, whatever the model thinks
            rules.absorb(keep, other)
            dropped.add(id(other))
    return [c for c in cands if id(c) not in dropped]
