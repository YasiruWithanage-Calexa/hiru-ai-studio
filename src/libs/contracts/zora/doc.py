"""Zora's document (plan/2026-11-06e §4.1): one scene's stored plan, the scene's script, and the person's marks.

    ZoraDoc(plan, scene, person)
        plan     the planner's plan as stored (`scenes.<planner>.plan`): treatment, sequences, shots, added, staging,
                 end_state. Plain JSON: Zora reads it as data and reaches the planner's own checks by id.
        scene    the scene as the planner is given it (numbered blocks, the cast, the place). READ-ONLY to every model.
        person   what a person set (`locked`: no model may write it) and handed over (`settled`: never asked again).

`shape_errors(plan, scene)` is the planner's wire validation in pure code (types and closed lists): the kernel re-checks
the whole plan after every operation and rolls back one that breaks it. The planner's own validation is run on top by
the kernel step, by id.

Pure standard library + pydantic (the `contracts` rule).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from contracts.zora.ops import ADDED_KINDS, FACINGS, FRAME_SIDES, LINKS, SIZES, TAKES, code


class Person(BaseModel):
    """What a person decided on this plan (`StoredPlan.person`, JSONB, plan §4.7). Paths are `ops.path_of` addresses
    with shot numbers as the plan stands (the kernel renumbers them with the shots)."""

    model_config = ConfigDict(extra="forbid")

    locked: list[str] = []  # a field a person set or confirmed: "not this", for any model
    settled: list[str] = []  # a choice the person handed over ("you decide the lens"): never asked about again

    def is_locked(self, path: str) -> bool:
        """A lock on `S03` covers every field of S03; a lock on `treatment` covers the whole treatment."""
        return any(path == p or path.startswith(p + ".") for p in self.locked)


class ZoraDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: dict[str, Any]
    scene: dict[str, Any]
    person: Person = Person()

    # ── reading ───────────────────────────────────────────────────────────────────────────────

    @property
    def shots(self) -> list[dict[str, Any]]:
        return list(self.plan.get("shots") or [])

    @property
    def sequences(self) -> list[dict[str, Any]]:
        return list(self.plan.get("sequences") or [])

    @property
    def blocks(self) -> list[dict[str, Any]]:
        return sorted(self.scene.get("blocks") or [], key=lambda b: int(b.get("index") or 0))

    @property
    def lines(self) -> dict[str, dict[str, Any]]:
        """line id (L4) → its block: the words are the script's and are never written by Zora."""
        return {str(b["line_id"]): b for b in self.blocks if b.get("kind") == "dialogue" and b.get("line_id")}

    @property
    def cast(self) -> list[str]:
        return [str(c) for c in self.scene.get("cast") or []]

    def shot_range(self) -> str:
        n = len(self.shots)
        return f"{code(1)}–{code(n)}" if n > 1 else code(1) if n == 1 else "no shots"

    def sequence_ids(self) -> list[str]:
        return [str(q.get("id")) for q in self.sequences]

    def has_shots(self) -> bool:
        return bool(self.shots)


# ── the planner's wire validation, in pure code ────────────────────────────────────────────────────


def _str(where: str, value: Any, out: list[str]) -> None:
    if not isinstance(value, str):
        out.append(f"{where} must be words")


def _int(where: str, value: Any, out: list[str]) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        out.append(f"{where} must be a whole number")


def _keys(where: str, value: Any, keys: tuple[str, ...], out: list[str]) -> bool:
    if not isinstance(value, dict):
        out.append(f"{where} must be an object")
        return False
    missing = [k for k in keys if k not in value]
    extra = [k for k in value if k not in keys and k != "_h"]
    if missing:
        out.append(f"{where} lacks {', '.join(missing)}")
    if extra:
        out.append(f"{where} has unknown {', '.join(extra)}")
    return not missing


SHOT_KEYS = ("n", "sequence", "blocks", "lines", "over", "size", "angle", "lens", "take_s", "use_s", "link", "why",
             "ir", "sound")


def shape_errors(plan: dict[str, Any], scene: dict[str, Any] | None = None) -> list[str]:
    """Everything that would make the planner's wire refuse this plan, as sentences ([] = it reads). With `scene`, a
    shot's blocks and lines must be the scene's."""
    out: list[str] = []
    if not _keys("the plan", plan, ("treatment", "sequences", "shots", "added", "staging", "end_state"), out):
        return out
    t = plan["treatment"]
    if _keys("the treatment", t, ("logline", "arc", "approach", "colour_script", "geography", "key_image", "advice"),
             out):
        for f in ("logline", "approach", "geography", "key_image"):
            _str(f"the treatment's {f}", t[f], out)
        for i, a in enumerate(t["arc"] if isinstance(t["arc"], list) else [], start=1):
            if _keys(f"arc beat {i}", a, ("beat", "blocks", "feeling"), out):
                _keys(f"arc beat {i}'s blocks", a["blocks"], ("first", "last"), out)
        for c in t["colour_script"] if isinstance(t["colour_script"], list) else []:
            _keys("a colour entry", c, ("sequence", "palette", "light", "grade"), out)
    ids = []
    for q in plan["sequences"] if isinstance(plan["sequences"], list) else []:
        if _keys("a sequence", q, ("id", "title", "purpose", "shots"), out):
            ids.append(q["id"])
            _keys(f"sequence {q['id']}'s shots", q["shots"], ("first", "last"), out)
    if len(ids) != len(set(ids)):
        out.append("two sequences share an id")
    blocks = {int(b["index"]) for b in (scene or {}).get("blocks") or []}
    lines = {str(b["line_id"]) for b in (scene or {}).get("blocks") or [] if b.get("line_id")}
    shots = plan["shots"] if isinstance(plan["shots"], list) else []
    if not isinstance(plan["shots"], list):
        out.append("the shots must be a list")
    for i, s in enumerate(shots, start=1):
        where = code(i)
        if not _keys(where, s, SHOT_KEYS, out):
            continue
        _int(f"{where}'s number", s["n"], out)
        if s["size"] not in SIZES:
            out.append(f"{where}'s size {s['size']!r} is not one of {', '.join(SIZES)}")
        if s["take_s"] not in TAKES:
            out.append(f"{where}'s take {s['take_s']!r} s is not one of 4, 6, 8")
        _int(f"{where}'s kept seconds", s["use_s"], out)
        if s["link"] not in LINKS:
            out.append(f"{where}'s link {s['link']!r} is not one of {', '.join(LINKS)}")
        for f in ("over", "angle", "lens", "why", "sequence"):
            _str(f"{where}'s {f}", s[f], out)
        if s["sequence"] not in ids:
            out.append(f"{where} belongs to sequence {s['sequence']!r}, which the plan does not have")
        if not isinstance(s["ir"], dict):
            out.append(f"{where}'s camera design must be an object")
        if _keys(f"{where}'s sound", s["sound"], ("ambience", "effects", "music", "silence"), out) and not isinstance(
                s["sound"]["silence"], bool):
            out.append(f"{where}'s silence must be true or false")
        if not isinstance(s["blocks"], list) or not isinstance(s["lines"], list):
            out.append(f"{where}'s blocks and lines must be lists")
        elif scene is not None:
            if any(b not in blocks for b in s["blocks"]):
                out.append(f"{where} shows a block the scene does not have")
            if any(ln not in lines for ln in s["lines"]):
                out.append(f"{where} names a line the scene does not have")
    numbers = [s.get("n") for s in shots if isinstance(s, dict)]
    for a in plan["added"] if isinstance(plan["added"], list) else []:
        if _keys("an addition", a, ("shot", "kind", "what", "who", "object"), out):
            if a["kind"] not in ADDED_KINDS:
                out.append(f"an addition's kind {a['kind']!r} is not one of the planner's")
            if a["shot"] not in numbers:
                out.append(f"an addition names shot {a['shot']}, which the plan does not have")
    st = plan["staging"]
    if _keys("the staging", st, ("zones", "marks"), out):
        for m in st["marks"] if isinstance(st["marks"], list) else []:
            if _keys("a staging mark", m, ("block", "who", "zone", "facing", "frame_side", "holding"), out):
                if m["facing"] not in FACINGS:
                    out.append(f"a mark's facing {m['facing']!r} is not one of {', '.join(f for f in FACINGS if f)}")
                if m["frame_side"] not in FRAME_SIDES:
                    out.append(f"a mark's frame side {m['frame_side']!r} is not one of left, right, centre")
    end = plan["end_state"]
    if _keys("the end state", end, ("people", "props", "time", "light"), out):
        for p in end["people"] if isinstance(end["people"], list) else []:
            _keys("a person at the end", p, ("who", "where", "facing", "holding", "look"), out)
    return out
