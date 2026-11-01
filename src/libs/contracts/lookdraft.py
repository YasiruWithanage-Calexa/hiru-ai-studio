"""Draft looks from a character's card (pure; the structure build and the API both use it).

A look is a person's wording (`routers/looks.py`), but a drama's bible already says what each
character wears and how that changes ("Later, as his business grows, clean smart-casual
clothing"). The build turns that into DRAFT looks so the character page is not empty:

* nothing is invented: a character whose card says nothing about clothes gets no look;
* a draft never affects a frame: only a READY look is used (`resolve_look`), and a person marks it
  ready once they have seen its sheet;
* a character that already has a look is left alone, so a re-run never doubles or overwrites.

Rules here; the model (with a key) proposes better splits and `clean_proposals` checks them.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from contracts.canon import EpisodeRange, LookFields, name_key

MAX_LOOKS = 4
# Where the wardrobe turns to "later": after a full stop or semicolon, or a capitalised "Later," mid-text.
_LATER = re.compile(r"(?:(?:^|[.;:\n])\s*(?i:later|eventually|in later episodes|by the end)\b"
                    r"|\s(?:Later|Eventually)\b(?=\s*[,:]))[\s,:-]*")
_GARMENT = re.compile(r"\b(shirts?|t-shirts?|dress(?:es)?|blouses?|trousers|jeans|saree|sari|sarong|skirts?|jackets?|"
                      r"coats?|uniform|frock|kurta|sandals|shoes|sneakers|polo|suit|cardigan|housecoat)\b",
                      re.IGNORECASE)
_ACCESSORY = re.compile(r"\b(jewel(?:le)?ry|earrings?|necklace|bracelets?|bangles?|watch|glasses|sunglasses|"
                        r"handbag|bag|caps?|hats?|scarf|belt|rings?|pendant)\b", re.IGNORECASE)
_HAIR = re.compile(r"\bhair\b", re.IGNORECASE)
_MAKEUP = re.compile(r"\bmake-?up\b", re.IGNORECASE)
_PIECES = re.compile(r"[;\n]|(?<=[a-z])\.\s+", re.IGNORECASE)
_SHORT = 80  # a hair or makeup note is a phrase; a longer segment is a whole description


def _clean(text: str) -> str:
    return " ".join((text or "").split()).strip(" .;,")


def _pieces(text: str) -> list[str]:
    return [p for p in (_clean(x) for x in _PIECES.split(text or "")) if p]


def _wardrobe_fields(wardrobe: str) -> tuple[str, str]:
    """(outfit, accessories): a piece that is only an accessory moves out of the outfit."""
    outfit: list[str] = []
    extras: list[str] = []
    for piece in _pieces(wardrobe):
        (extras if _ACCESSORY.search(piece) and not _GARMENT.search(piece) else outfit).append(piece)
    return "; ".join(outfit), "; ".join(extras)


def _noted(appearance: str, pattern: re.Pattern[str]) -> str:
    return "; ".join(p for p in _pieces(appearance) if len(p) <= _SHORT and pattern.search(p))


def _span(first: int, last: int) -> EpisodeRange:
    return EpisodeRange.model_validate({"from": first, "to": last})


def _fields(name: str, first: int, last: int, wardrobe: str, appearance: str) -> LookFields:
    outfit, accessories = _wardrobe_fields(wardrobe)
    return LookFields(name=name, ranges=[_span(first, last)], outfit=outfit[:600],
                      hair=_noted(appearance, _HAIR)[:300], makeup=_noted(appearance, _MAKEUP)[:300],
                      accessories=accessories[:600])


def by_rules(card: Mapping[str, Any], episodes: int) -> list[LookFields]:
    """One look for the whole drama, or two when the wardrobe says what they wear "later"."""
    wardrobe, appearance = _clean(str(card.get("wardrobe") or "")), str(card.get("appearance") or "")
    last = max(episodes, 1)
    if not wardrobe:
        return []
    found = _LATER.search(wardrobe)
    if found and found.start() > 0 and last >= 2:
        early, late = _clean(wardrobe[:found.start()]), _clean(wardrobe[found.end():])
        if early and late:
            turn = (last + 1) // 2  # "later" starts in the second half
            return [_fields("Everyday", 1, turn, early, appearance),
                    _fields("Later", turn + 1, last, late, appearance)]
    return [_fields("Everyday", 1, last, wardrobe, appearance)]


def clean_proposals(raw: Sequence[Mapping[str, Any]], episodes: int) -> list[LookFields]:
    """The model's looks for ONE character, kept only when they hold up: a name, at least one
    wardrobe field, ranges inside the drama, no repeated name. Anything else is dropped."""
    out: list[LookFields] = []
    seen: set[str] = set()
    last = max(episodes, 1)
    for item in raw:
        name = _clean(str(item.get("name") or ""))[:120]
        try:
            first, to = int(item.get("from") or 0), int(item.get("to") or 0)
        except (TypeError, ValueError):
            continue
        first, to = max(first, 1), min(to, last)
        values = {k: _clean(str(item.get(k) or "")) for k in ("outfit", "hair", "makeup", "accessories")}
        if not name or name_key(name) in seen or to < first or not any(values.values()):
            continue
        seen.add(name_key(name))
        out.append(LookFields(name=name, ranges=[_span(first, to)], outfit=values["outfit"][:600],
                              hair=values["hair"][:300], makeup=values["makeup"][:300],
                              accessories=values["accessories"][:600]))
    return out[:MAX_LOOKS]


def look_row(entity_id: str, production_id: str, look: LookFields, actor: str | None) -> dict[str, Any]:
    """A `canon_looks` row (a draft: the table's default status)."""
    return {"entity_id": entity_id, "production_id": production_id, "name": look.name,
            "ranges": [r.model_dump(by_alias=True) for r in look.ranges], "outfit": look.outfit, "hair": look.hair,
            "makeup": look.makeup, "accessories": look.accessories, "created_by": actor}
