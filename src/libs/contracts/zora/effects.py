"""What a turn can CHANGE, who can change it, and code's reading of whether it did (plan/2026-11-06e §4.6 step 5; Nova
W4/W7).

Nova's conductor used to pick a seat by how the message read, and nothing compared it with the change the person
wanted: "add a reaction" seated sound, the ledger truthfully recorded a change, the reply said "done", and no shot was
added. The phrasing space is unbounded; the things a request can change are not. So the conductor DECLARES effects from
this closed list, code checks each one against the diff (`changed_effects`), and what did not change is re-tasked once
and then reported as "asked for, not done", never claimed.

    WRITES[effect] = Effect(label, owner, ops)   owner: "author" (the one creative call), "conductor" (only the
                                                  person's own words: the end state), never a model for a lock
    changed_effects(before, after, scope=…)       the effects that differ between two plans exported WITH handles
                                                  (`_h` on every shot), a shot effect only on the shots in `scope`

Pure standard library.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from contracts.zora.ops import IR_FIELDS, OPS, SHOT_FIELDS, SOUND_FIELDS, TREATMENT_FIELDS


@dataclass(frozen=True)
class Effect:
    label: str  # how the reply names it to a person
    owner: str  # "author" | "conductor"
    ops: tuple[str, ...]  # the operations that can produce it


def _build() -> dict[str, Effect]:
    t: dict[str, Effect] = {}
    for f in TREATMENT_FIELDS:
        t[f"treatment.{f}"] = Effect(f"the treatment's {f.replace('_', ' ')}", "author", ("treatment.set",))
    t["treatment.arc"] = Effect("the emotional arc", "author", ("arc.set", "arc.add", "arc.remove"))
    t["treatment.colour"] = Effect("the colour script", "author", ("colour.set",))
    t["sequence.title"] = Effect("a sequence's title", "author", ("sequence.set",))
    t["sequence.purpose"] = Effect("a sequence's purpose", "author", ("sequence.set",))
    t["sequence.bounds"] = Effect("which shots each sequence holds", "author",
                                  ("sequence.bounds", "sequence.add", "sequence.remove", "regroup"))
    for f in SHOT_FIELDS:
        t[f"shot.{f}"] = Effect({"why": "the shots' reasons", "over": "who is seen while a line is heard"}.get(
            f, f"the shots' {f}"), "author", ("set",))
    t["shot.take_s"] = Effect("the takes' lengths", "author", ("retime",))
    t["shot.use_s"] = Effect("the seconds the edit keeps", "author", ("use",))
    for f in SOUND_FIELDS:
        t[f"shot.sound.{f}"] = Effect(f"the shots' {'silence' if f == 'silence' else f}", "author", ("sound.set",))
    for f in IR_FIELDS:
        t[f"shot.ir.{f}"] = Effect(f"the shots' {f.replace('_', ' ')} (camera design)", "author", ("ir.set",))
    t["shot.order"] = Effect("which shots there are (split, merged, added, removed, moved)", "author",
                             ("split", "merge", "insert", "remove", "move"))
    t["shot.added"] = Effect("the shots the director added", "author", ("insert", "remove"))
    t["staging.marks"] = Effect("who stands where", "author", ("mark.set", "mark.add", "mark.remove"))
    t["staging.zones"] = Effect("the places on the set", "author", ("zone.add",))
    t["end_state"] = Effect("how the scene ends (what the next scene starts from)", "conductor", ("end.set",))
    return t


WRITES: dict[str, Effect] = _build()
_ALIASES = {"approach": "treatment.approach", "logline": "treatment.logline", "geography": "treatment.geography",
            "key_image": "treatment.key_image", "arc": "treatment.arc", "colour": "treatment.colour",
            "colour_script": "treatment.colour", "color": "treatment.colour", "staging": "staging.marks",
            "end": "end_state", "lighting": "shot.ir.lighting", "camera": "shot.ir.cinematography",
            "movement": "shot.ir.cinematography", "shots": "shot.order", "structure": "shot.order",
            "sequences": "sequence.bounds"}


def normalize_effect(name: object) -> str:
    """A declared effect as a WRITES key, or "" (unknown names are dropped, never guessed at)."""
    text = str(name or "").strip().strip("`'\"").lower()
    text = _ALIASES.get(text, text)
    if text.startswith("shot.ir.") and text.split(".")[2] in IR_FIELDS:
        text = ".".join(text.split(".")[:3])  # shot.ir.cinematography.movement → shot.ir.cinematography
    if text not in WRITES and f"shot.{text}" in WRITES:
        text = f"shot.{text}"
    return text if text in WRITES else ""


def can_produce(by: str, effect: str) -> bool:
    """Could `by`'s operations change this effect at all?"""
    spec = WRITES.get(effect)
    return spec is not None and any(by in OPS[op][1] for op in spec.ops)


def label(effect: str) -> str:
    spec = WRITES.get(effect)
    return spec.label if spec else effect


# ── code's reading of the diff ─────────────────────────────────────────────────────────────────────


def _shots(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(s.get("_h") or f"#{i}"): s for i, s in enumerate(plan.get("shots") or [])}


def _shot_effects(old: dict[str, Any] | None, new: dict[str, Any]) -> set[str]:
    """The shot effects that differ (a new shot: every one it has a value for)."""
    out: set[str] = set()
    base = old or {}
    for f in SHOT_FIELDS:
        if new.get(f) != base.get(f) and (old is not None or new.get(f)):
            out.add(f"shot.{f}")
    for f, key in (("take_s", "take_s"), ("use_s", "use_s")):
        if old is not None and new.get(key) != base.get(key):
            out.add(f"shot.{f}")
    for f in SOUND_FIELDS:
        if (new.get("sound") or {}).get(f) != (base.get("sound") or {}).get(f) and (old is not None or
                                                                                    (new.get("sound") or {}).get(f)):
            out.add(f"shot.sound.{f}")
    for f in IR_FIELDS:
        if (new.get("ir") or {}).get(f) != (base.get("ir") or {}).get(f) and (old is not None or
                                                                              (new.get("ir") or {}).get(f)):
            out.add(f"shot.ir.{f}")
    return out


def changed_effects(before: dict[str, Any], after: dict[str, Any], scope: set[str] | None = None) -> set[str]:
    """Which effects differ between two plans. Shots are paired by HANDLE, never by position (one insert earlier in
    the turn would shift every comparison). A shot effect counts only on a shot in `scope` (handles; None = any)."""
    out: set[str] = set()
    tb, ta = before.get("treatment") or {}, after.get("treatment") or {}
    for f in TREATMENT_FIELDS:
        if tb.get(f) != ta.get(f):
            out.add(f"treatment.{f}")
    if _plain(tb.get("arc")) != _plain(ta.get("arc")):
        out.add("treatment.arc")
    if tb.get("colour_script") != ta.get("colour_script"):
        out.add("treatment.colour")
    qb = {q["id"]: q for q in before.get("sequences") or []}
    qa = {q["id"]: q for q in after.get("sequences") or []}
    for f in ("title", "purpose"):
        if any(qb.get(k, {}).get(f) != q.get(f) for k, q in qa.items()):
            out.add(f"sequence.{f}")
    sb, sa = _shots(before), _shots(after)
    if {h: s.get("sequence") for h, s in sb.items() if h in sa} != {h: s.get("sequence") for h, s in sa.items()
                                                                    if h in sb} or set(qb) != set(qa):
        out.add("sequence.bounds")
    if list(sb) != list(sa) or any(sb[h].get("blocks") != s.get("blocks") for h, s in sa.items() if h in sb):
        out.add("shot.order")
    for h, s in sa.items():
        if scope is None or h in scope:
            out |= _shot_effects(sb.get(h), s)
    if _added(before) != _added(after):
        out.add("shot.added")
    st_b, st_a = before.get("staging") or {}, after.get("staging") or {}
    if st_b.get("marks") != st_a.get("marks"):
        out.add("staging.marks")
    if st_b.get("zones") != st_a.get("zones"):
        out.add("staging.zones")
    if before.get("end_state") != after.get("end_state"):
        out.add("end_state")
    return out


def _plain(arc: Any) -> Any:
    return [{k: v for k, v in a.items() if k != "_h"} for a in arc or []]


def _added(plan: dict[str, Any]) -> list[tuple[str, str, str]]:
    return sorted((str(a.get("kind")), str(a.get("what")), ",".join(a.get("who") or [])) for a in plan.get("added")
                  or [])
