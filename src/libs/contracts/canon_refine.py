"""Canon refine (plan/2026-11-12c §3): ONE call reads the finished breakdown and writes real canon cards.

The breakdown is pointer-only (the model points, code copies), so the canon cards it fills are the documents' words: an
age that is the whole cast-list sentence, a place card that is a whole scene. The `breakdown_canon` agent reads the
breakdown memory and writes what each person, place and thing LOOKS like; every value says where it came from (`script`
with its line, `inferred` with a reason). This module is everything around that call, pure, so the agent, the job and
the tests send and check the same bytes:

- `message(bd, lines, canon, ids)`  what the agent reads: each entity's card lines and the lines of its scenes
                                    (numbered as the breakdown numbers them, deduplicated), the breakdown's entities,
                                    the scenes' briefs, the palette and lighting rules, the continuity looks, and what a
                                    person wrote
- `parts(...)`                      the ids split so each message stays under a budget (people, then places and things)
- `Answer`, `json_schema()`         the strict answer shape
- `check(answer, bd, lines, ids)`   code checks (report only; `fix` findings go to one repair call)
- `repair_message`, `merge`         the repair call for the failed ids alone, and its answer merged back by id
- `versions(...)`                   the answer as new canon versions, entity classes and parents for the
                                    write (`canon_refine_apply`, schema v23)

Ported from `lab/canon_refine/` (run1, run2: 2026-11-12). No model, no database.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from contracts import safe_depiction
from contracts.breakdown.packet import SUMMARY_MAX_LINES, _pretty
from contracts.breakdown.schema import Breakdown, Entity
from contracts.canon import CanonCard, CanonKind, name_key, reference_sheet_prompt, voice_pin, wardrobe_anchor

Row = dict[str, Any]
RULE_ABOUT = ("palette", "lighting")
CANON_KIND = {"person": "character", "place": "location", "thing": "prop"}
BREAKDOWN_KIND = {v: k for k, v in CANON_KIND.items()}
BUDGET_TOKENS = 40_000  # one message's size before the call is split (§3.1 "Scale")
# the version sources a refine may replace without a person's say (D2): anything else becomes a proposal
REPLACEABLE = ("extract", "inferred", "refine")
PLACE_CLASSES = ("set", "vehicle", "region", "spot", "unseen")
THING_CLASSES = ("prop", "mentioned")
PLATED = ("set", "vehicle")  # a region, a spot or an unseen place is never painted as one plate


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Value(_M):
    value: str
    source: Literal["script", "inferred"]
    line: int  # the document line a `script` value was read from; 0 when inferred
    reason: str  # why, for an inferred value; "" for script


class Person(_M):
    id: str
    gender: Value  # "man" | "woman"
    age: Value  # a number or a short range ("30", "late 20s")
    appearance: Value  # face, build, skin tone, hair: what a camera needs to cast and repeat them
    wardrobe: Value  # the base everyday wardrobe for who they are
    voice: Value  # timbre and manner


class Place(_M):
    id: str
    kind: Literal["set", "vehicle", "region", "spot", "unseen"]
    parent: str  # for a spot: the L id of the set or vehicle it is part of; else ""
    look: Value  # sets and vehicles: the place itself, with no people; others: "" or a short note
    why: str  # one line: why this kind


class Thing(_M):
    id: str
    kind: Literal["prop", "mentioned"]  # prop: a camera sees it; mentioned: only talked about or noted
    details: Value  # colour, size, material, condition


class Answer(_M):
    people: list[Person]
    places: list[Place]
    things: list[Thing]


def _strict(node: Any, defs: dict[str, Any]) -> Any:
    """Pydantic's schema -> OpenAI strict: refs inlined, every property required, no extra properties."""
    if isinstance(node, dict):
        if "$ref" in node:
            return _strict(defs[node["$ref"].split("/")[-1]], defs)
        out = {k: _strict(v, defs) for k, v in node.items() if k not in ("title", "$defs", "default")}
        if out.get("type") == "object":
            out["required"] = list(out.get("properties", {}))
            out["additionalProperties"] = False
        return out
    if isinstance(node, list):
        return [_strict(v, defs) for v in node]
    return node


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    return dict(_strict(raw, raw.get("$defs", {})))


def json_schema() -> dict[str, Any]:
    return strict_schema(Answer)


# ── the message ──────────────────────────────────────────────────────────────────────────────────────────────────────


def approx_tokens(text: str) -> int:
    """A cautious size: about three characters a token (Sinhala costs more than English; the budget is a guard)."""
    return len(text) // 3 + 1


def scenes_of(bd: Breakdown) -> dict[str, list[str]]:
    """entity id -> the scene ids the breakdown puts it in (place, people, things, event spots and actors)."""
    found: dict[str, list[str]] = {}

    def add(eid: str, sid: str) -> None:
        if eid and sid not in found.setdefault(eid, []):
            found[eid].append(sid)

    for sc in bd.scenes:
        b = sc.brief or {}
        add(str(b.get("place") or ""), sc.id)
        for p in b.get("people", []):
            add(str(p.get("person") or ""), sc.id)
        for t in b.get("things", []):
            add(str(t.get("thing") or ""), sc.id)
        for blk in sc.blocks:
            if blk.get("speaker"):
                add(str(blk["speaker"]), sc.id)
            for ev in blk.get("events", []) or []:
                add(str(ev.get("spot") or ""), sc.id)
                for a in ev.get("actors", []) or []:
                    add(str(a), sc.id)
                for t in ev.get("things", []) or []:
                    add(str(t), sc.id)
    return found


def _canon_row_of(e: Entity, canon: list[Row], canon_ids: dict[str, str] | None = None) -> Row | None:
    """The canon entity a breakdown entity filled: by the stored map first (Track B), then by kind and name."""
    if canon_ids and e.id in canon_ids:
        got = next((c for c in canon if str(c["id"]) == canon_ids[e.id]), None)
        if got is not None:
            return got
    kind, key = CANON_KIND[e.kind], name_key(_pretty(e.name))
    return next(
        (
            c
            for c in canon
            if c["kind"] == kind and key in {name_key(n) for n in [c["name"], *(c.get("aliases") or [])]}
        ),
        None,
    )


def canon_map(bd: Breakdown, canon: list[Row], canon_ids: dict[str, str] | None = None) -> dict[str, str]:
    """breakdown id -> canon entity id, for every entity the canon has."""
    out = {}
    for e in bd.entities:
        row = _canon_row_of(e, canon, canon_ids)
        if row is not None:
            out[e.id] = str(row["id"])
    return out


def person_written(e: Entity, canon: list[Row], canon_ids: dict[str, str] | None = None) -> Row:
    """The non-empty fields of a card a PERSON wrote for this entity (their words win and are context, never
    rewritten). Locked alone is not a person's words: Ekama's locked cast still holds the extracted text."""
    row = _canon_row_of(e, canon, canon_ids)
    current = (row or {}).get("current") or {}
    if current.get("source") != "user":
        return {}
    return {k: v for k, v in (current.get("card") or {}).items() if v}


def wanted_lines(bd: Breakdown, ids: list[str]) -> list[int]:
    """Each entity's card lines and the lines of every scene it is in, once each, in order."""
    in_scenes = scenes_of(bd)
    scenes = {s.id: s for s in bd.scenes}
    keep: set[int] = set()
    for eid in ids:
        e = bd.entity(eid)
        if e is None:
            continue
        keep.update(range(e.lines[0], e.lines[1] + 1))
        for sid in in_scenes.get(eid, []):
            sc = scenes.get(sid)
            if sc is not None:
                keep.update(range(sc.heading_line, sc.last + 1))
    return sorted(keep)


def numbered(lines: list[str], keep: list[int]) -> list[str]:
    """The kept lines numbered as the breakdown numbers them; a gap is shown as one `…` line."""
    out: list[str] = []
    last = 0
    for n in keep:
        if not 1 <= n <= len(lines):
            continue
        if last and n != last + 1:
            out.append("    …")
        out.append(f"{n:>4}| {lines[n - 1]}")
        last = n
    return out


def build(
    bd: Breakdown,
    lines: list[str],
    canon: list[Row],
    ids: list[str] | None = None,
    canon_ids: dict[str, str] | None = None,
) -> Row:
    """The data the agent reads, for the entities `ids` (all of them by default)."""
    ids = ids if ids is not None else [e.id for e in bd.entities]
    names = {e.id: _pretty(e.name) for e in bd.entities}
    in_scenes = scenes_of(bd)
    entities = []
    for eid in ids:
        e = bd.entity(eid)
        if e is None:
            continue
        item: Row = {
            "id": e.id,
            "kind": e.kind,
            "name": names[e.id],
            "card_lines": list(e.lines),
            "seen": e.seen,
            "scenes": in_scenes.get(e.id, []),
        }
        if e.kind == "place":
            item["place_kind"] = e.place_kind
            item["within"] = f"{e.within} {names.get(e.within, '')}".strip() if e.within else ""
        summary = e.card.get("summary")
        if summary is not None and summary.source == "inferred":
            item["implied"] = summary.value
        wrote = person_written(e, canon, canon_ids)
        if wrote:
            item["a_person_wrote"] = wrote
        entities.append(item)
    wanted = set(ids)
    scenes = []
    for sc in bd.scenes:
        b = sc.brief or {}
        involved = (
            {str(b.get("place") or "")}
            | {str(p.get("person")) for p in b.get("people", [])}
            | {str(t.get("thing")) for t in b.get("things", [])}
        )
        if not (involved & wanted) and not any(sc.id in in_scenes.get(i, []) for i in wanted):
            continue
        scenes.append(
            {
                "id": sc.id,
                "heading": sc.heading,
                "lines": [sc.heading_line, sc.last],
                "place": b.get("place", ""),
                "mood": b.get("mood", []),
                "people": [p.get("person") for p in b.get("people", [])],
                "things": [f"{t.get('thing')} ({t.get('role')})" for t in b.get("things", [])],
            }
        )
    places = {e.id for e in bd.entities if e.kind == "place"}
    rules = [
        {
            "id": r.id,
            "about": r.about,
            "text": r.text,
            "applies_to": names.get(r.scope_id, r.scope_id) if r.scope_id in places else r.scope_kind,
        }
        for r in bd.rules
        if r.about in RULE_ABOUT
    ]
    cont = bd.continuity or {}
    people = {i for i in ids if i.startswith("C")}
    return {
        "document": numbered(lines, wanted_lines(bd, ids)),
        "entities": entities,
        "scenes": scenes,
        "direction_rules": rules,
        "continuity": {
            "looks": [lk for lk in cont.get("looks", []) if not people or lk.get("person") in people],
            "timeline": [
                {k: t.get(k) for k in ("scene", "story_order", "kind", "relative")} for t in cont.get("timeline", [])
            ],
        },
    }


def message(
    bd: Breakdown,
    lines: list[str],
    canon: list[Row],
    ids: list[str] | None = None,
    canon_ids: dict[str, str] | None = None,
) -> str:
    data = build(bd, lines, canon, ids, canon_ids)
    doc = "\n".join(data.pop("document"))
    return (
        f"THE DOCUMENTS (numbered lines)\n{doc}\n\nTHE BREAKDOWN (JSON)\n"
        f"{json.dumps(data, ensure_ascii=False, indent=1)}"
    )


def parts(
    bd: Breakdown,
    lines: list[str],
    canon: list[Row],
    budget: int = BUDGET_TOKENS,
    canon_ids: dict[str, str] | None = None,
) -> list[list[str]]:
    """The ids in as few calls as fit the budget: all at once, else people, then places and things, then halves."""
    every = [e.id for e in bd.entities]

    def fits(ids: list[str]) -> bool:
        return approx_tokens(message(bd, lines, canon, ids, canon_ids)) <= budget

    def split(ids: list[str]) -> list[list[str]]:
        if len(ids) <= 1 or fits(ids):
            return [ids] if ids else []
        half = len(ids) // 2
        return split(ids[:half]) + split(ids[half:])

    if fits(every):
        return [every]
    people = [e.id for e in bd.entities if e.kind == "person"]
    rest = [e.id for e in bd.entities if e.kind != "person"]
    return split(people) + split(rest)


# ── checks (report only) ─────────────────────────────────────────────────────────────────────────────────────────────

WORD = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
STOP = {"the", "and", "with", "a", "an", "of", "in", "on", "to", "his", "her", "is", "at", "for", "only", "when"}
ID = re.compile(r"\b[CLP]\d{2,3}\b")  # a breakdown id written inside a description
# the model explaining itself inside a value (lab run1: "weak overcast light avoids fixing an unstated hour"). Not
# "supports": run2's garage had "steel supports", a real building word.
REASONING = re.compile(
    r"\b(suggests?|avoids?|avoiding|impl(?:y|ies|ied)|because|in order to|unstated|"
    r"establish(?:es|ed)?|to show|indicates?)\b",
    re.IGNORECASE,
)
# a script gender is read from a word like these on its line ("a faded photo of him and Aruni")
GENDERED = {
    "man": {"he", "him", "his", "himself", "man", "brother", "son", "father", "husband", "boy", "mr"},
    "woman": {"she", "her", "hers", "herself", "woman", "sister", "daughter", "mother", "wife", "girl", "mrs"},
}
GENDER_WORDS = {"male": "man", "man": "man", "female": "woman", "woman": "woman"}


@dataclass
class Finding:
    id: str  # the entity id (a repair is sent for these alone)
    code: str  # missing | unknown | duplicate | script | gender | id | reasoning | people | parent | safe
    message: str
    level: str = "fix"  # fix: sent to the repair call | review: shown to a person


def words(text: str) -> set[str]:
    return {w for w in WORD.findall(text.lower()) if w not in STOP}


def script_ok(v: Value, lines: list[str]) -> str:
    """'' when a `script` value holds up against the line it names, else why not. An inferred value is not checked."""
    if v.source != "script":
        return ""
    if not 1 <= v.line <= len(lines):
        return f"says script line {v.line}, which does not exist"
    line = lines[v.line - 1].lower()
    digits = re.findall(r"\d+", v.value)
    if digits and not all(d in line for d in digits):
        return f"says {v.value!r} is on line {v.line}, but the line has no {', '.join(digits)}"
    own = words(v.value)
    if own and not digits:
        shared = len(own & words(line)) / len(own)
        if shared < 0.5:
            return f"says {v.value!r} is read from line {v.line}, but most of its words are not on that line"
    return ""


def gender_ok(v: Value, lines: list[str]) -> str:
    """A script gender holds up when its line has a gendered word of that gender (he, him, she, brother...)."""
    if v.source != "script":
        return ""
    if not 1 <= v.line <= len(lines):
        return f"says script line {v.line}, which does not exist"
    said = GENDER_WORDS.get(v.value.strip().lower(), "")
    if said and not (GENDERED[said] & set(WORD.findall(lines[v.line - 1].lower()))):
        return (
            f"says {v.value!r} is read from line {v.line}, but that line has no word like {sorted(GENDERED[said])[:4]}"
        )
    return ""


def _values(item: BaseModel) -> list[tuple[str, Value]]:
    return [(k, v) for k, v in item if isinstance(v, Value)]


def check(answer: Answer, bd: Breakdown, lines: list[str], ids: list[str] | None = None) -> list[Finding]:
    """Every finding on the answer for the entities `ids` (all by default). Nothing is edited here."""
    ents = {e.id: e for e in bd.entities}
    asked = set(ids if ids is not None else ents)
    out: list[Finding] = []
    seen: dict[str, int] = {}
    for group, kind in (("people", "person"), ("places", "place"), ("things", "thing")):
        for item in getattr(answer, group):
            seen[item.id] = seen.get(item.id, 0) + 1
            if item.id not in ents or item.id not in asked:
                out.append(Finding(item.id, "unknown", f"{item.id} is not one of the ids you were given"))
            elif ents[item.id].kind != kind:
                out.append(Finding(item.id, "unknown", f"{item.id} is a {ents[item.id].kind}, answered as a {kind}"))
    for eid, n in seen.items():
        if n > 1:
            out.append(Finding(eid, "duplicate", f"{eid} is answered {n} times"))
    for eid in ents:
        if eid in asked and eid not in seen:
            out.append(Finding(eid, "missing", f"{eid} {_pretty(ents[eid].name)} has no answer"))

    # who a place look may not name: every person's name and its words (Nimal, Inspector Ruwan -> ruwan)
    people = {_pretty(e.name).lower() for e in ents.values() if e.kind == "person"}
    person_words = {w for n in people for w in n.split() if len(w) > 3 and w not in {"inspector"}}

    items: list[Person | Place | Thing] = [*answer.people, *answer.places, *answer.things]
    for item in items:
        for field, v in _values(item):
            why = gender_ok(v, lines) if field == "gender" else script_ok(v, lines)
            if why:
                out.append(Finding(item.id, "script", f"{item.id} {field}: {why}"))
            if found := sorted(set(ID.findall(v.value))):
                out.append(
                    Finding(item.id, "id", f"{item.id} {field}: writes {', '.join(found)}; write the names instead")
                )
            if m := REASONING.search(v.value):
                out.append(
                    Finding(
                        item.id,
                        "reasoning",
                        f"{item.id} {field}: says {m.group(0)!r}, which explains a choice; the value only describes, "
                        "the reason goes in `reason`",
                    )
                )
            for f in safe_depiction.blocking(v.value):
                out.append(Finding(item.id, "safe", f"{item.id} {field}: says {f.said!r}; write {f.instead}"))
    for p in answer.people:
        if len(p.age.value) > 14 or not re.search(r"\d", p.age.value):  # "30", "late 40s"; never the cast-list sentence
            out.append(Finding(p.id, "script", f"{p.id} age {p.age.value!r} is not a short age"))
        if p.gender.value.strip().lower() not in GENDER_WORDS:
            out.append(Finding(p.id, "gender", f"{p.id} gender {p.gender.value!r} is not man or woman"))
    places = {x.id: x for x in answer.places}
    for pl in answer.places:
        look = pl.look.value.lower()
        named = sorted(w for w in person_words if re.search(rf"\b{re.escape(w)}\b", look))
        if named:
            out.append(Finding(pl.id, "people", f"{pl.id} look names {', '.join(named)}: a place look shows no people"))
        if pl.kind in PLATED and len(words(look)) < 8:
            out.append(Finding(pl.id, "people", f"{pl.id} is a {pl.kind} but its look is too thin to paint"))
        if pl.kind == "spot":
            owner = places.get(pl.parent)
            parent_kind = owner.kind if owner else (ents[pl.parent].place_kind if pl.parent in ents else None)
            if parent_kind not in PLATED:
                out.append(
                    Finding(pl.id, "parent", f"{pl.id} is a spot but its parent {pl.parent!r} is not a set or vehicle")
                )
    return out


def fixes(found: list[Finding]) -> list[Finding]:
    return [f for f in found if f.level == "fix"]


# ── the repair call ──────────────────────────────────────────────────────────────────────────────────────────────────


def repair_message(user: str, answer: Answer, found: list[Finding]) -> str:
    """The first message again, the failed entries and what the checks said: answer for those ids alone."""
    ids = sorted({f.id for f in found})
    bad = {
        "people": [p.model_dump() for p in answer.people if p.id in ids],
        "places": [p.model_dump() for p in answer.places if p.id in ids],
        "things": [t.model_dump() for t in answer.things if t.id in ids],
    }
    return (
        f"{user}\n\nYOUR EARLIER ANSWER FOR THESE IDS FAILED A CHECK\n{json.dumps(bad, ensure_ascii=False, indent=1)}"
        "\n\nTHE CHECKS SAID\n"
        + "\n".join(f"- {f.message}" for f in found)
        + f"\n\nAnswer again for ONLY these ids: {', '.join(ids)}. Fix exactly what the checks say; keep the rest."
    )


def merge(answer: Answer, fixed: Answer) -> Answer:
    """`answer` with each entry `fixed` answers replaced by id (and any it adds)."""

    def by_id(old: list[Any], new: list[Any]) -> list[Any]:
        repl = {x.id: x for x in new}
        have = {o.id for o in old}
        return [repl.get(x.id, x) for x in old] + [x for x in new if x.id not in have]

    return Answer(
        people=by_id(answer.people, fixed.people),
        places=by_id(answer.places, fixed.places),
        things=by_id(answer.things, fixed.things),
    )


def join(answers: list[Answer]) -> Answer:
    """The answers of a split call as one (each part answers its own ids)."""
    out = Answer(people=[], places=[], things=[])
    for a in answers:
        out = merge(out, a)
    return out


# ── the answer as canon versions (for `canon_refine_apply`, schema v23) ──────────────────────────────────────────────


def summary_of(e: Entity) -> str:
    """The card's summary as fill keeps it: the documents' words, but never a range wider than the packet shows
    (`SUMMARY_MAX_LINES`), so a card is never a whole scene."""
    v = e.card.get("summary")
    if v is None:
        return ""
    if e.lines[1] - e.lines[0] + 1 > SUMMARY_MAX_LINES and v.source != "inferred":
        return ""
    return " ".join(str(v.value).split())


LIMITS = {
    "summary": 2000,
    "age": 60,
    "gender": 40,
    "appearance": 600,
    "wardrobe": 600,
    "voice": 300,
    "accent": 120,
    "look": 800,
    "details": 800,
    "notes": 2000,
}  # contracts.canon.CanonCard's max lengths


def _limit(card: Row) -> CanonCard:
    return CanonCard.model_validate({k: str(v)[: LIMITS[k]] for k, v in card.items() if k in LIMITS})


def card_hash(card: CanonCard) -> str:
    return hashlib.sha256(json.dumps(card.model_dump(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _prov(fields: dict[str, Value]) -> Row:
    return {
        k: {"source": v.source, "line": v.line if v.source == "script" else 0, "reason": v.reason}
        for k, v in fields.items()
        if v.value.strip()
    }


def versions(
    answer: Answer,
    bd: Breakdown,
    canon: list[Row],
    *,
    aspect_ratio: str = "16:9",
    actor: str | None = None,
    canon_ids: dict[str, str] | None = None,
) -> list[Row]:
    """One new version per entity the answer refined and the canon has: the current card with the refined fields in,
    the pins and the reference prompt rebuilt by the existing builders, `source: refine`, the provenance of each field,
    and the version the job READ (`expected_version_id`), so the switch is refused if a person changed it since. The
    entity's class and parent ride along. An entity the canon does not have is left out (fill creates it)."""
    rows: list[Row] = []
    items: list[Person | Place | Thing] = [*answer.people, *answer.places, *answer.things]
    by_id: dict[str, Any] = {x.id: x for x in items}
    canon_of: dict[str, Row] = {}
    for e in bd.entities:
        got = _canon_row_of(e, canon, canon_ids)
        if got is not None:
            canon_of[e.id] = got
    for e in bd.entities:
        item, row = by_id.get(e.id), canon_of.get(e.id)
        if item is None or row is None:
            continue
        current = row.get("current") or {}
        card: Row = {k: v for k, v in (current.get("card") or {}).items() if v}
        if current.get("source") != "user":  # a person's summary stays; an extracted one is cut like fill's
            card["summary"] = summary_of(e)
        fields: dict[str, Value] = {}
        cls: str | None = None
        parent = ""
        if isinstance(item, Person):
            fields = {k: getattr(item, k) for k in ("gender", "age", "appearance", "wardrobe", "voice")}
        elif isinstance(item, Place):
            fields = {"look": item.look}
            cls, parent = item.kind, item.parent
            region = by_id.get(e.within)
            if item.kind in PLATED and isinstance(region, Place) and region.kind == "region":
                parent = e.within  # a set's region: its look is the set's style note
        elif isinstance(item, Thing):
            fields = {"details": item.details}
            cls = item.kind
        for k, v in fields.items():  # the model was shown what a person wrote and built around it (`a_person_wrote`)
            text = " ".join(v.value.split())
            if text:
                card[k] = text
        new = _limit(card)
        kind = CanonKind(row["kind"])
        character = kind is CanonKind.CHARACTER
        name = str(row["name"])
        rows.append(
            {
                "entity_id": str(row["id"]),
                "expected_version_id": str(row.get("current_version_id") or current.get("id") or "") or None,
                "card": new.model_dump(),
                "card_hash": card_hash(new),
                "wardrobe_anchor": wardrobe_anchor(new) if character else "",
                "voice_pin": voice_pin(new) if character else "",
                "reference_prompt": reference_sheet_prompt(kind, name, new, aspect_ratio=aspect_ratio),
                "provenance": _prov(fields),
                "created_by": actor,
                "class": cls,
                "parent_id": str(canon_of[parent]["id"]) if parent and parent in canon_of else None,
                "breakdown_id": e.id,
            }
        )
    return rows


def plated(cls: str | None) -> bool:
    """A reference plate is painted only for a set, a vehicle, or a place no refine has classed yet."""
    return not cls or cls in (*PLATED, "prop")


def no_plate_reason(cls: str | None) -> str:
    return {
        "region": "A region is never painted as one plate: its sets are. Its look is their style note.",
        "spot": "A spot is part of a set: paint the set it belongs to.",
        "unseen": "This place is only mentioned and needs no picture.",
        "mentioned": "This thing is only mentioned and needs no picture.",
    }.get(str(cls or ""), "")
