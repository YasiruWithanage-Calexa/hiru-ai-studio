"""canon_rules: documents in, canon candidates found by rules alone.

    {"documents": [{"filename": "bible.md", "role": "bible", "text": "..."}]}   roles: script | canon_index | bible

`rule_candidates` and `chips` are the canon builder's own (ported from `canon_extract/engine/pipeline.py`); `critic` is
the free check from `write.py`: what a person should fill in before shots are written.
"""
from __future__ import annotations

from typing import Any

from contracts.canon import CanonKind
from contracts.screenplay import parse_document
from hiru_ai.steps.canon_rules import logic as rules

SCRIPT, INDEX, BIBLE = "script", "canon_index", "bible"


def rule_candidates(documents: list[dict[str, str]]) -> list[rules.Candidate]:
    index = [c for d in documents if d["role"] == INDEX for c in rules.from_index(d["text"], d["filename"])]
    bible = [c for d in documents if d["role"] == BIBLE for c in rules.from_bible(d["text"], d["filename"])]
    known = {n for c in [*index, *bible] for n in [c["name"], *c["aliases"]]}
    parsed = [(d["filename"], parse_document(d["text"], d["filename"], known))
              for d in documents if d["role"] == SCRIPT]
    return rules.drop_uncertain_places(rules.merge(index, bible, rules.from_scripts(parsed)))


def chips(cands: list[rules.Candidate]) -> list[str]:
    chars = [c for c in cands if c["kind"] == CanonKind.CHARACTER]
    core = sum(1 for c in chars if c["core"])
    out = [f"{core} core characters", f"{len(chars) - core} supporting",
           f"{sum(1 for c in cands if c['kind'] == CanonKind.LOCATION)} locations",
           f"{sum(1 for c in cands if c['kind'] == CanonKind.PROP)} props"]
    return [c for c in out if not c.startswith("0 ")]


def critic(cands: list[rules.Candidate]) -> list[str]:
    """What a person should fill in before shots are written. Free and deterministic."""
    notes = []
    for c in cands:
        if c["kind"] != CanonKind.CHARACTER.value or not c["core"]:
            continue
        wanted = (("wardrobe", "wardrobe anchor"), ("voice", "voice"))
        missing = [label for key, label in wanted if not c["card"].get(key)]
        if missing:
            notes.append(f"{c['code'] or c['name']}: no {' or '.join(missing)} in the documents yet.")
    return notes


def run(payload: dict[str, Any]) -> dict[str, Any]:
    found = rule_candidates(payload.get("documents") or [])
    return {"candidates": found, "chips": chips(found), "notes": critic(found)}
