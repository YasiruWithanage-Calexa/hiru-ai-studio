"""What happens to a scene before its shots are planned: the code halves of `script_split`'s `beats.py`, `reading.py`,
`staging.py` and the pipeline's `prepare`, `scene_context` and `stage` (plan/2026-11-03 Phase 6).

The model calls are agents (`beat_finder`, `scene_reader`, `stager`). Here each is an `ask(items) -> answer | raises`
the system closes over, so the control flow is the engine's own: a missing key (`ask` is None), a failed call or an
unusable answer falls back to the free rules, block by block, and a person's marks are never replaced.

    prepare   the script with its implied steps in and every action block read for this script version
    reading   a scene's reading: a person's is kept, a current one is kept, else the model's validated or the rules'
    staging   the people's places: the same, with no rules (no map means nothing about places is checked)
    stage     walk anyone who would teleport: one removable step each, remembered when a person removed it
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from contracts import beats as screen_beats
from contracts import bridges, sceneplan
from contracts import reading as rd
from contracts import stagemap as sm
from contracts.beats import MAX_EVENTS, Reading, read_by_rules
from contracts.shotplan import Item
from contracts.timing import SCREEN_KINDS

_logger = logging.getLogger(__name__)
Row = dict[str, Any]
Ask = Callable[[list[Item]], Row]  # the agent's answer for these items, as the plain data the validators read


# ── what each action block shows (beats.py) ─────────────────────────────────────────────────


def validate_beats(answer: Row, items: list[Item]) -> dict[int, Reading]:
    """The model's readings for action blocks it was asked about; anything else is dropped."""
    actions = {i.index for i in items if i.kind == "action" and not i.implied and i.by != "person"}
    out: dict[int, Reading] = {}
    for row in answer.get("blocks", []):
        try:
            index, screen, events = int(row["block"]), str(row["screen"]), int(row["events"])
        except (KeyError, TypeError, ValueError):
            continue
        if index in actions and screen in SCREEN_KINDS:
            out[index] = Reading(screen, max(1, min(MAX_EVENTS, events)))
    return out


def classify(ask: Ask | None, items: list[Item]) -> tuple[dict[int, Reading], str]:
    """-> (a reading for every action block, who made them: "model" or "rules").

    With no `ask` (no key) the rules read everything. A model answer is taken block by block; the rules read any block
    it left out, so the clock never misses one."""
    rules = read_by_rules(items)
    if ask is None or not rules:
        return rules, "rules"
    try:
        answer = ask(items)
    except Exception:
        _logger.warning("beat classifier failed; using the rules", exc_info=True)
        return rules, "rules"
    model = validate_beats(answer, items)
    if not model:
        return rules, "rules"
    return {**rules, **model}, "model"


def prepare(scene: Row, lines: list[Row], ask: Ask | None, cast: list[str] | None = None
            ) -> tuple[list[Row], list[Item]]:
    """-> (the scene's script with its implied steps in and every action block read for this script version, the kernel
    items for it). Blocks that already carry a reading for this version are not read again; a person's marks are never
    replaced."""
    version = int(scene.get("script_version") or 1)
    script = bridges.with_bridges(scene.get("script") or [], lines, version, cast or ())
    items = sceneplan.items_for(script, lines)
    if screen_beats.is_stale(items, version):
        readings, by = classify(ask, items)
        script = screen_beats.annotate(script, lines, readings, version, by)
        items = sceneplan.items_for(script, lines)
    return script, items


# ── the scene's reading (reading.py) ────────────────────────────────────────────────────────


def make_reading(ask: Ask | None, items: Sequence[Item], cast: Sequence[str], *, version: int) -> rd.SceneReading:
    """A reading for these items: the model's, validated; the free rules' when there is no `ask`, the call fails, or the
    answer has nothing usable in it."""
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    if ask is not None and items:
        try:
            made = rd.validate(ask(list(items)), items, cast, version=version, by="model")
            if made.about or made.units:
                return made.model_copy(update={"written_at": stamp})
        except Exception:
            _logger.warning("scene reading failed; using the rules", exc_info=True)
    return rd.by_rules(items, cast, version=version).model_copy(update={"written_at": stamp})


def reading_for(scene: Row, items: Sequence[Item], ask: Ask | None, cast: Sequence[str]
                ) -> tuple[rd.SceneReading, bool]:
    """-> (the scene's reading, was it just made?). A person's reading is kept as it is (stale or not: the person
    decides); one made for these blocks and this script version is kept; anything else is made again."""
    version = int(scene.get("script_version") or 1)
    stored = rd.SceneReading.of(scene)
    if stored is not None and (stored.by == "person" or not stored.stale(items, version)):
        return stored, False
    return make_reading(ask, items, cast, version=version), True


# ── where the people are (staging.py) ───────────────────────────────────────────────────────


def make_staging(ask: Ask | None, items: Sequence[Item], cast: Sequence[str], *,
                 version: int) -> sm.SceneStaging | None:
    """A map for these items: the model's, validated. None when there is no `ask`, the call fails, or the answer has no
    usable marks (the scene is then checked for nothing about places)."""
    if ask is None or not items:
        return None
    try:
        made = sm.validate(ask(list(items)), items, cast, version=version, by="model")
    except Exception:
        _logger.warning("scene staging failed; the scene is not checked for places", exc_info=True)
        return None
    if not made.marks:
        return None
    return made.model_copy(update={"written_at": datetime.now(UTC).isoformat(timespec="seconds")})


def staging_for(scene: Row, items: Sequence[Item], ask: Ask | None, cast: Sequence[str]
                ) -> tuple[sm.SceneStaging | None, bool]:
    """-> (the scene's map or None, was it just made?). A person's map is kept as it is; one made for these blocks and
    this script version is kept; anything else is made again."""
    version = int(scene.get("script_version") or 1)
    stored = sm.SceneStaging.of(scene)
    if stored is not None and (stored.by == "person" or not stored.stale(items, version)):
        return stored, False
    made = make_staging(ask, items, cast, version=version)
    return made, made is not None


def stage(scene: Row, lines: list[Row], script: list[Row], items: list[Item], reading: rd.SceneReading,
          ask: Ask | None, names: dict[str, str]
          ) -> tuple[list[Row], list[Item], rd.SceneReading, sm.SceneStaging | None]:
    """Place the scene's people, then walk anyone who would teleport (plan/2026-11-01d, Phase 4).

    -> (the script with its implied moves in, its items, the reading and the map carried across those blocks, the map or
    None). CODE finds each person who changes zone with nothing to show the way and adds one removable step for each,
    unless a person removed it before. Without a key or without marks there is no map and nothing about places is
    checked."""
    cast = list(names.values())
    staging, _ = staging_for(scene, items, ask, cast)
    moves = sm.plan_moves(staging, items, cast)
    if staging is None or not moves:
        return script, items, reading, staging
    script, where = bridges.insert_moves(script, lines, moves, int(scene.get("script_version") or 1))
    placed = sceneplan.items_for(script, lines)
    if reading.basis == rd.basis(items):  # a person's out-of-date reading keeps the numbers it had
        reading = rd.remap(reading, placed, where)
    return script, placed, reading, sm.remap(staging, placed, where)


# ── what surrounds a scene ──────────────────────────────────────────────────────────────────


def scene_context(scene: Row, episodes: dict[str, Row], neighbours: list[Row], cards: list[tuple[str, str]]) -> Row:
    """What surrounds a scene, for the reading and the planner: its episode, the scenes either side in that episode, the
    director's note, the characters' cards. Plain data: the `scene_reader`'s context, and `context_text` for the
    planner."""
    episode = episodes.get(str(scene.get("episode_id"))) or {}
    siblings = sorted((n for n in neighbours if str(n.get("episode_id")) == str(scene.get("episode_id"))),
                      key=lambda n: int(n.get("number") or 0))

    def gist(row: Row | None) -> str:
        if not row:
            return ""
        return " — ".join(p for p in (str(row.get("heading") or ""), str(row.get("title") or "")) if p)

    number = int(scene.get("number") or 0)
    before = next((n for n in reversed(siblings) if int(n.get("number") or 0) < number), None)
    after = next((n for n in siblings if int(n.get("number") or 0) > number), None)
    return {"heading": str(scene.get("heading") or ""), "note": str(scene.get("note") or ""),
            "episode_title": str(episode.get("title") or ""), "synopsis": str(episode.get("synopsis") or ""),
            "before": gist(before), "after": gist(after),
            "characters": [{"name": name, "summary": summary} for name, summary in cards]}


def context_text(c: Row) -> str:
    """The context as the planner reads it (the engine's `SceneContext.text()`)."""
    rows = [f"Scene: {c['heading']}" if c["heading"] else "",
            f"Director's note: {c['note']}" if c["note"] else "",
            f"Episode: {c['episode_title']}" if c["episode_title"] else "",
            f"Episode synopsis: {c['synopsis']}" if c["synopsis"] else "",
            f"The scene before: {c['before']}" if c["before"] else "",
            f"The scene after: {c['after']}" if c["after"] else ""]
    rows += [f"Character {p['name']}: {p['summary']}" if p["summary"] else f"Character {p['name']}"
             for p in c["characters"]]
    return "\n".join(r for r in rows if r)


def location_notes(locations: list[Row]) -> dict[str, str]:
    """location id -> "Name: what the place is", for the staging map's spots. No locations gives none."""
    return {str(r["id"]): " — ".join(p for p in (str(r.get("name") or ""), str(
        ((r.get("current") or {}).get("card") or {}).get("summary") or "")) if p) for r in locations}


def scene_uuid(scene: Row) -> UUID:
    return UUID(str(scene["id"]))
