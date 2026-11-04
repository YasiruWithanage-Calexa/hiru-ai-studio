"""Reads that several tools show the same way: a canon item, a look, a shot and what it was made against.

Pure functions over the rows a port returned. They hold the rule once (how a person names a thing, when a design or a
prompt is out of date) so `canon_read` and `shot_read` cannot disagree about it. What a model reads uses codes and
numbers (`C02`, `L01`, `S03`, `E1S2`), never ids."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from contracts import sceneplan
from contracts.canon import name_key, resolve_look
from contracts.producer import (
    CastMember,
    PersonEdits,
    Pins,
    pins_for,
    shot_items,
    stale_reasons,
)
from contracts.shotplan import Item
from contracts.staging import shot_cast
from hiru_ai.core.ports import Row


def cast_member(row: Row) -> CastMember:
    current = row.get("current") or {}
    card = current.get("card") or {}
    return CastMember(id=str(row["id"]), code=str(row["code"]), name=str(row["name"]), kind=str(row["kind"]),
                      version=current.get("version"), wardrobe_anchor=str(current.get("wardrobe_anchor") or ""),
                      voice_pin=str(current.get("voice_pin") or ""), appearance=str(card.get("appearance") or ""),
                      gender=str(card.get("gender") or ""))


# ── canon ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


def find_entity(canon: Iterable[Row], ref: str) -> Row | None:
    """The canon item a person means by `ref`: its code, its name or one of its aliases (case and spacing forgiven)."""
    key = name_key(ref)
    for entity in canon:
        names = {name_key(str(entity["code"])), name_key(str(entity["name"])),
                 *(name_key(str(a)) for a in entity.get("aliases") or [])}
        if key in names:
            return entity
    return None


def entity_names(canon: Iterable[Row]) -> list[str]:
    """Every name and code a model could have meant, for "did you mean"."""
    out: list[str] = []
    for entity in canon:
        out += [str(entity["code"]), str(entity["name"]), *(str(a) for a in entity.get("aliases") or [])]
    return out


def card_summary(entity: Row) -> str:
    """One line on what the card says: the appearance of a person, the look of a place."""
    card = (entity.get("current") or {}).get("card") or {}
    for key in ("appearance", "look", "description"):
        if card.get(key):
            return str(card[key])
    return next((str(v) for v in card.values() if isinstance(v, str) and v), "")


def episodes_text(ranges: Sequence[Mapping[str, Any]]) -> str:
    """[{"from": 1, "to": 3}, {"from": 44, "to": 44}] → "1-3, 44"."""
    return ", ".join(str(r["from"]) if r["from"] == r["to"] else f"{r['from']}-{r['to']}" for r in ranges)


def look_view(look: Row) -> Row:
    return {"name": look.get("name", ""), "episodes": episodes_text(look.get("ranges") or []),
            "outfit": look.get("outfit", ""), "hair": look.get("hair", ""), "makeup": look.get("makeup", ""),
            "accessories": look.get("accessories", ""), "status": look.get("status", "")}


def look_in(looks: Sequence[Row], entity: Row, episode: int) -> Row | None:
    """The look `entity` wears in `episode` (the episode rule: the person's own pick for one scene is not a tool's)."""
    found = resolve_look([lk for lk in looks if str(lk["entity_id"]) == str(entity["id"])], episode)
    return dict(found) if found is not None else None


# ── shots and what they were made against ────────────────────────────────────────────────────────────────────────────


def shot_by_number(shots: Iterable[Row], number: int) -> Row | None:
    return next((s for s in shots if int(s["number"]) == number), None)


class MadeAgainst:
    """What a shot is made against NOW (its pins) and the canon by id, to hold a design or a prompt up to."""

    def __init__(self, scene: Row, shot: Row, lines: list[Row], canon: list[Row]) -> None:
        self.items: list[Item] = sceneplan.scene_items(scene, lines)
        characters = [c for c in canon if c["kind"] == "character"]
        self.members = {str(c["id"]): cast_member(c) for c in canon}
        own = shot_items(self.items, int(shot["block_start"]), int(shot["block_end"]))
        self.cast_ids = shot_cast(own, characters, shot)
        self.version = int(shot.get("version") or 1)
        self.now: Pins = pins_for(shot_version=self.version, scene=scene, items=own, cast_ids=self.cast_ids,
                                  versions={k: m.version for k, m in self.members.items()},
                                  edits=PersonEdits.of(shot))

    def reasons(self, made: Mapping[str, Any] | None) -> list[str]:
        """Why something made against `made` (a design's or prompt's pins) is out of date now; [] when it is current."""
        if not made:
            return []
        out = stale_reasons(made, shot_version=self.version, script_hash=self.now.script_hash, canon=self.members)
        if set(Pins.model_validate(made).canon) != set(self.now.canon) and not out:
            out.append("Different people or place in the shot.")
        return out


def timing_view(result: Any, *, detailed: bool = False) -> dict[str, Any]:
    """A `shotplan.fit` result as a model reads it: each shot's start and length, when each spoken line starts and by
    how much it overruns, and the issues. One formatter for `timing_check` and for the director's `get_shot_timing`."""
    from hiru_ai.core.tooling import shot_code

    return {
        "total_s": result.total_s, "envelope_s": result.envelope_s, "silent_s": result.silent_s,
        "over_envelope_s": result.over_envelope_s,
        "shots": [{"shot": shot_code(s.number), "start_s": s.start_s, "length_s": s.duration_s,
                   "sound": s.sound_mode.value, "words": s.words, "word_target": s.word_target,
                   **({"blocks": f"{s.start}-{s.end - 1}", "framing": s.framing, "join": s.camera_link.value,
                       "need_s": s.need_s} if detailed else {})} for s in result.shots],
        "lines": [{"shot": shot_code(ln.shot_number), "starts_s": ln.start_s, "overrun_s": ln.overrun_s}
                  for ln in result.lines],
        "issues": [{"code": i.code, "message": i.message,
                    **({"shot": shot_code(i.shot_number)} if i.shot_number else {})} for i in result.issues]}


# ── what a model sends: a plan to think about, and operations to try ─────────────────────────────────────────────────


class ShotProposal(BaseModel):
    """One shot of a plan being thought about (block ranges and hints); the kernel fits it to the clock."""

    start: int = Field(ge=0, description="First block index (inclusive)")
    end: int = Field(ge=1, description="Last block index (exclusive)")
    framing: str = "MS"
    title: str = ""
    sound_mode: str | None = None
    duration: int | None = Field(None, description="A length hint (4, 6 or 8), exact when duration_locked")
    duration_locked: bool = False
    camera_link: str = "cut"


def fitted_rows(scene: Row, lines: list[Row], proposals: Sequence[ShotProposal],
                fixed_seconds: int | None = None) -> list[Row]:
    """A proposed plan as stored-shot rows (what `kernel_score` and `stage_check` read), with the lengths the clock
    gives."""
    from contracts.shotplan import ProposedShot, fit

    items = sceneplan.scene_items(scene, lines)
    result = fit(items, [ProposedShot(p.start, p.end, p.framing, p.title, p.sound_mode, p.duration, p.duration_locked,
                                      p.camera_link) for p in proposals],
                 envelope_s=int(scene["envelope_s"]), fixed_seconds=fixed_seconds)
    return [{"id": f"proposed-{s.number}", "number": s.number, "block_start": s.start, "block_end": s.end,
             "framing": s.framing, "title": s.title, "sound_mode": s.sound_mode.value, "duration_s": s.duration_s,
             "camera_link": s.camera_link.value, "duration_locked": False, "status": "draft", "version": 1}
            for s in result.shots]


def cast_names(canon: Iterable[Row]) -> list[str]:
    """Names of the production's people, for the checks that look for who an action names."""
    return [str(c["name"]) for c in canon if c["kind"] == "character"]


class ToolOp(BaseModel):
    """One operation of the kernel's closed set, as a model writes it: `op` and only the fields that op uses. (The
    director's own `Op` asks for every field, null or not, because its wire schema is strict; a tool's is not.)"""

    op: Literal["set", "retime", "unlock_length", "split", "merge", "regroup", "set_join", "beat.set", "insert",
    "remove",
                "set_envelope", "block.set", "block.insert", "block.remove", "canon.add", "canon.remove", "check.waive",
                "check.restore", "dop_note.set"]
    shot: int | None = Field(None, description="The shot's number (2 for S02)")
    field: str | None = Field(None, description="The field `set` or `beat.set` changes, like framing or sound_mode")
    value: str | None = None
    seconds: int | None = None
    at_block: int | None = None
    end_block: int | None = None
    link: str | None = None
    beat: int | None = None
    after_shot: int | None = None
    description: str | None = None
    framing: str | None = None
    title: str | None = None
    block: int | None = None
    kind: str | None = None
    speaker: str | None = None
    delivery: str | None = None


def op_dicts(ops: Sequence[ToolOp]) -> list[dict[str, Any]]:
    """The operations as the kernel reads them: every field present, the unused ones null."""
    from contracts.directorops import OP_FIELDS

    return [{"op": o.op, **dict.fromkeys(OP_FIELDS), **o.model_dump(exclude_none=True, exclude={"op"})} for o in ops]
