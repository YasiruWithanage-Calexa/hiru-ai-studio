"""Canon from the documents by rule: free, deterministic, and enough to build a production
without a model.

Sources, most authoritative first:
1. a CANON INDEX (`C01 Kamala (කමලා) — mother, 52. … Voice: …`): codes, names, aliases, cards;
2. the BIBLE's character sections (`### Kamala (කමලා) — the mother`), with "Wardrobe anchor:";
3. SCRIPTS: every speaker cue is a character, every scene heading's place a location.

Candidates are plain dicts (they travel through the LangGraph state):
    {key, kind, code, name, aliases, core, card, sources, lines, scenes}
"""
from __future__ import annotations

import re
from typing import Any

from contracts.canon import CanonKind, name_key
from contracts.screenplay import ParsedDocument

Candidate = dict[str, Any]

_INDEX_LINE = re.compile(r"^\s*(?:[-*•]\s*)?\**([CLP]\d{2,3})\**[\s.:)\-–—]+(.+?)(?:\s*:\s+|\s+[—–\-]\s+)(.+)$")
_ALIAS = re.compile(r"\(([^)]+)\)")
_BIBLE_CHAR = re.compile(r"^\s*#{2,4}\s+(.+?)\s*(?:[—–\-:]\s*(.+))?$")
_SECTION = re.compile(r"^\s*#{1,3}\s+(.+?)\s*$")
_AGE = re.compile(r"\b(\d{1,2}s?|\d{1,2}\s*-\s*\d{1,2})\b")
_CLOTHES = re.compile(r"\b(saree|sari|shirt|t-shirt|sarong|dress|blouse|cardigan|housecoat|jacket|trousers|"
                      r"uniform|frock|skirt|kurta|cap|hat|watch|glasses|sandals|shoes|coat|wears?|wardrobe|"
                      r"cotton|linen|silk)\b", re.IGNORECASE)
_FEMALE = re.compile(r"\b(mother|woman|girl|wife|daughter|sister|aunt|grandmother|widow|she|her|mrs|miss|"
                     r"amma|akka|nangi)\b", re.IGNORECASE)
_MALE = re.compile(r"\b(father|man|boy|husband|son|brother|uncle|grandfather|widower|he|his|mr|"
                   r"thaththa|aiya|malli)\b", re.IGNORECASE)


def display_name(raw: str) -> str:
    """"KAMALA'S HOUSE" → "Kamala's House"; mixed-case and Sinhala names are kept as written."""
    raw = " ".join(raw.split()).strip(" .*")
    if raw != raw.upper():
        return raw
    return " ".join(w[:1].upper() + w[1:].lower() for w in raw.split())


def _split_name(text: str) -> tuple[str, list[str]]:
    aliases = [a.strip() for a in _ALIAS.findall(text) if a.strip()]
    name = _ALIAS.sub(" ", text).strip(" *")
    return display_name(name), aliases


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", " ".join(text.split())) if s.strip()]


def card_from_text(kind: CanonKind, text: str) -> dict[str, str]:
    """A card from free description. Labelled parts ("Voice:", "Wardrobe anchor:") are exact;
    the rest is a best effort the model path improves on."""
    card: dict[str, str] = {}
    if kind is not CanonKind.CHARACTER:
        card["look" if kind is CanonKind.LOCATION else "details"] = " ".join(text.split())
        card["summary"] = _sentences(text)[0] if text.strip() else ""
        return card
    summary: list[str] = []
    wardrobe: list[str] = []
    other: list[str] = []
    for s in _sentences(text):
        low = s.lower()
        if low.startswith("voice:"):
            parts = [p.strip(" .") for p in s.split(":", 1)[1].split(",")]
            accent = [p for p in parts if "accent" in p.lower()]
            card["voice"] = ", ".join(p for p in parts if p and p not in accent)
            if accent:
                card["accent"] = accent[0]
        elif low.startswith(("wardrobe anchor:", "wardrobe:")):
            wardrobe.append(s.split(":", 1)[1].strip(" ."))
        elif _CLOTHES.search(s) and summary:
            wardrobe.append(s.strip(" ."))
        elif not summary:
            summary.append(s.strip(" ."))
        else:
            other.append(s.strip(" ."))
    head = " ".join(summary)
    card["summary"] = head
    if m := _AGE.search(head):
        card["age"] = m.group(1)
    female, male = bool(_FEMALE.search(head)), bool(_MALE.search(head))
    if female != male:
        card["gender"] = "female" if female else "male"
    if wardrobe:
        card["wardrobe"] = "; ".join(wardrobe)
    if other:
        card["appearance"] = " ".join(other)[:600]
    return card


def candidate(kind: CanonKind, name: str, *, code: str = "", aliases: list[str] | None = None,
               core: bool = False, card: dict[str, str] | None = None, source: str = "") -> Candidate:
    return {"key": f"{kind.value}:{name_key(name)}", "kind": kind.value, "code": code, "name": name,
            "aliases": list(dict.fromkeys(aliases or [])), "core": core, "card": dict(card or {}),
            "sources": [source] if source else [], "lines": 0, "scenes": 0}


def from_index(text: str, filename: str) -> list[Candidate]:
    out = []
    for line in text.split("\n"):
        m = _INDEX_LINE.match(line)
        if not m:
            continue
        code, name_part, desc = m.group(1), m.group(2), m.group(3)
        kind = {"C": CanonKind.CHARACTER, "L": CanonKind.LOCATION, "P": CanonKind.PROP}[code[0]]
        name, aliases = _split_name(name_part)
        out.append(candidate(kind, name, code=code, aliases=aliases, core=kind is CanonKind.CHARACTER,
                              card=card_from_text(kind, desc), source=filename))
    return out


def from_bible(text: str, filename: str) -> list[Candidate]:
    """Characters under a "Characters" section, one `###` heading each."""
    out: list[Candidate] = []
    in_chars = False
    current: Candidate | None = None
    body: list[str] = []

    def close() -> None:
        if current is None:
            return
        found = card_from_text(CanonKind.CHARACTER, " ".join(body))
        role = current["card"].get("summary", "")  # the heading's "the mother" leads
        if role and found.get("summary"):
            found["summary"] = f"{role}. {found['summary']}"
        elif role:
            found["summary"] = role
        current["card"] = found
        out.append(current)

    for line in text.split("\n"):
        stripped = line.strip()
        level = len(stripped) - len(stripped.lstrip("#"))
        if level in (1, 2) and _SECTION.match(stripped):
            close()
            current, body = None, []
            in_chars = "character" in stripped.lower() or "cast" in stripped.lower()
            continue
        if in_chars and level >= 3 and (m := _BIBLE_CHAR.match(stripped)):
            close()
            name, aliases = _split_name(m.group(1))
            role = (m.group(2) or "").strip()
            current = candidate(CanonKind.CHARACTER, name, aliases=aliases, core=True,
                                 card={"summary": role} if role else {}, source=filename)
            body = []
        elif current is not None and stripped:
            body.append(stripped)
    close()
    return out


def from_scripts(parsed: list[tuple[str, ParsedDocument]]) -> list[Candidate]:
    chars: dict[str, Candidate] = {}
    places: dict[str, Candidate] = {}
    for filename, doc in parsed:
        for scene in doc.scenes:
            loc = scene.heading.location
            if loc:
                c = places.setdefault(name_key(loc), candidate(CanonKind.LOCATION, display_name(loc),
                                                                aliases=[loc], source=filename))
                c["scenes"] += 1
            for block in scene.blocks:
                if block.kind != "dialogue" or not block.speaker:
                    continue
                c = chars.setdefault(name_key(block.speaker), candidate(
                    CanonKind.CHARACTER, display_name(block.speaker), aliases=[block.speaker], source=filename))
                c["lines"] += 1
            for speaker in scene.speakers:
                chars[name_key(speaker)]["scenes"] += 1
    return [*chars.values(), *places.values()]


def _keys(c: Candidate) -> set[str]:
    return {name_key(c["name"]), *(name_key(a) for a in c["aliases"])} - {""}


def _tokens(key: str) -> set[str]:
    return {t for t in key.split() if len(t) > 1 and t not in {"the", "s", "of"}}


def same(a: Candidate, b: Candidate) -> bool:
    if a["kind"] != b["kind"]:
        return False
    if a["code"] and b["code"]:
        return bool(a["code"] == b["code"])
    if _keys(a) & _keys(b):
        return True
    if a["kind"] == CanonKind.LOCATION.value:
        # "Kalugala harbour" (a heading) is the index's "Kalugala harbour breakwater".
        for ka in _keys(a):
            for kb in _keys(b):
                ta, tb = _tokens(ka), _tokens(kb)
                if ta and tb and (ta <= tb or tb <= ta):
                    return True
    return False


def absorb(into: Candidate, other: Candidate) -> None:
    """Merge `other` into `into` (which has priority): fill empty card fields, union aliases."""
    into["code"] = into["code"] or other["code"]
    for alias in [other["name"], *other["aliases"]]:
        if name_key(alias) not in _keys(into):
            into["aliases"].append(alias)
    for k, v in other["card"].items():
        if v and not into["card"].get(k):
            into["card"][k] = v
    into["core"] = into["core"] or other["core"]
    into["sources"] = list(dict.fromkeys([*into["sources"], *other["sources"]]))
    into["lines"] += other["lines"]
    into["scenes"] += other["scenes"]


def drop_uncertain_places(cands: list[Candidate]) -> list[Candidate]:
    """Leave out places known only from scene headings that share words with another location
    ("Kalugala beach" beside "Kalugala harbour breakwater"): same place or not is a person's
    call, and the structure build asks it. Creating it here would answer it silently."""
    places = [c for c in cands if c["kind"] == CanonKind.LOCATION.value]

    def heading_only(c: Candidate) -> bool:
        return not c["code"] and not c["card"].get("look")

    def overlaps(a: Candidate, b: Candidate) -> bool:
        return any(_tokens(ka) & _tokens(kb) for ka in _keys(a) for kb in _keys(b))

    drop = {id(c) for c in places if heading_only(c)
            and any(o is not c and not heading_only(o) and overlaps(c, o) for o in places)}
    return [c for c in cands if id(c) not in drop]


def merge(*groups: list[Candidate]) -> list[Candidate]:
    """Earlier groups win. Each candidate joins the first earlier one it is the same as."""
    out: list[Candidate] = []
    for group in groups:
        for cand in group:
            match = next((c for c in out if same(c, cand)), None)
            if match is None:
                out.append({**cand, "aliases": list(cand["aliases"]), "card": dict(cand["card"]),
                            "sources": list(cand["sources"])})
            else:
                absorb(match, cand)
    return out
