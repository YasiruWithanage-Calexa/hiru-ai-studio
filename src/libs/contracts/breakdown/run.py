"""The creation run (plan/2026-11-11 §4): pure code, with its model calls passed in.

    1 split        one call per document (four at a time)  -> the source memory of each document
    2 build        code: the documents laid end to end, cards merged, ids, rules, scenes
    3 continuity   ONE call over every episode
    4 episodes     one call per group of up to six scenes of one episode (four at a time)
    5 checks       code; a scene with a blocking finding goes back to the same model with its own answer and the
                   exact problems, at most twice, and a patch that is not better is never kept
    (6 the stager runs per scene before planning: `stage_message` / `stage.apply`, not here)

After a person edits a scene's script, `refresh_scene` runs steps 4 and 5 for that one scene on the person's words and
reports a hand-over the next scene in the story no longer matches.

Absent-safe (§3.6): a failed split leaves that document out (and says so); a failed continuity call leaves the
continuity facts empty; a failed episode call leaves its scenes without a brief, each with a blocking finding, so their
packets wait and the production still opens. Every message is built here, so the graph's agents and any other caller
send the same bytes.
"""

from __future__ import annotations

import contextvars
import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from contracts.breakdown import build as build_mod
from contracts.breakdown import checks, inputs, memory
from contracts.breakdown import series as series_mod
from contracts.breakdown.lines import Doc
from contracts.breakdown.schema import (
    Breakdown,
    ContinuityW,
    EpisodeW,
    Finding,
    Scene,
    SeriesW,
    SourceMemory,
    SplitW,
)

_logger = logging.getLogger(__name__)
WORKERS = 4  # episodes are read four at a time (plan §10, phase 2)
SCENES_PER_CALL = 6  # Ekama: S04-S09 in one call was fine at medium effort (plan §4.4)
REPAIR_TRIES = 2
EMPTY_CONTINUITY: dict[str, Any] = {k: [] for k in ContinuityW.model_fields}
NL = "\n"


@dataclass
class Calls:
    """The model calls, each taking the user message this module built and returning the typed answer."""

    split: Callable[[str], SplitW]
    continuity: Callable[[str], ContinuityW]
    episode: Callable[[str], EpisodeW]
    repair: Callable[[str], EpisodeW]
    # plan/2026-11-12b: what the drama is (genre, tone, world, theme, premise); None = not read (the block stays empty)
    series: Callable[[str], SeriesW] | None = None


@dataclass
class Upload:
    """One uploaded document: its id, name, text (the reader's clean transcription in pages mode) and how it was
    read."""

    document_id: str
    filename: str
    text: str
    read_from: str = "text"


@dataclass
class Result:
    memory: Breakdown | None
    sources: list[SourceMemory] = field(default_factory=list)
    failed: str = ""  # why there is no memory at all
    notes: list[str] = field(default_factory=list)  # what a person should know (a document left out, a failed call)


def split_message(filename: str, d: Doc) -> str:
    """The document is data, inside labelled tags (CLAUDE.md, "AI and RAG"); its lines carry their numbers."""
    return f'<document filename="{filename}">\n{d.numbered()}\n</document>'


def _pool(fn: Callable[[Any], Any], items: list[Any], workers: int) -> list[Any]:
    """Each call in a copy of the caller's context (the model, the trace and the usage sink the caller set)."""
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(contextvars.copy_context().run, fn, x) for x in items]
        return [f.result() for f in futures]


def groups(bd: Breakdown) -> list[list[str]]:
    """The episode calls: each episode's scenes in page order, at most SCENES_PER_CALL per call."""
    out: list[list[str]] = []
    by_ep: dict[int, list[str]] = {}
    for s in bd.scenes:
        by_ep.setdefault(s.episode, []).append(s.id)
    for ep in sorted(by_ep):
        ids = by_ep[ep]
        n = -(-len(ids) // SCENES_PER_CALL)  # as few calls as the cap allows, the scenes shared out evenly
        size = -(-len(ids) // n)
        out += [ids[i : i + size] for i in range(0, len(ids), size)]
    return out


def episode_before(bd: Breakdown, d: Doc, first_scene: str) -> str:
    """The end of the episode before (the last lines of its last scene), as the document writes it."""
    sc = bd.scene(first_scene)
    if sc is None:
        return ""
    earlier = [s for s in bd.scenes if s.episode == sc.episode - 1]
    if not earlier:
        return ""
    last = earlier[-1]
    lo = max(last.first, last.last - 5)
    return f"{last.id} {last.heading}\n" + NL.join(f"{n}: {d.lines[n - 1]}" for n in range(lo, last.last + 1))


def repair_message(bd: Breakdown, d: Doc, cont: dict[str, Any], sc: Scene, problems: list[Finding]) -> str:
    prev = {
        "scene": sc.id,
        **(sc.brief or {}),
        "blocks": [
            {k: v for k, v in b.items() if k not in ("id", "text")}
            | {
                "spans": [{"line": a, "w_from": w0, "w_to": w1} for a, w0, w1 in b["spans"]],
                "events": [{k: v for k, v in e.items() if k != "id"} for e in b["events"]],
            }
            for b in sc.blocks
        ],
    }
    return (NL * 2).join(
        [
            inputs.episode_user(bd, d, cont, [sc.id]),
            "YOUR PREVIOUS ANSWER FOR THIS SCENE" + NL + json.dumps(prev, ensure_ascii=False),
            "PROBLEMS" + NL + NL.join(f"- {f.message}" for f in problems),
        ]
    )


def _blocking(bd: Breakdown, scene_id: str) -> list[Finding]:
    return [f for f in bd.findings if f.blocking and f.scene == scene_id]


def repair(
    bd: Breakdown,
    d: Doc,
    cont: dict[str, Any],
    calls: Calls,
    scene_ids: list[str],
    say: Callable[[str], None] = lambda _: None,
) -> list[str]:
    """Step 5's repair for the scenes named, one after another (each try re-runs every check). Returns notes."""
    notes: list[str] = []
    for sid in scene_ids:
        sc = bd.scene(sid)
        if sc is None or sc.brief is None:
            continue
        probs = _blocking(bd, sid)
        for attempt in range(1, REPAIR_TRIES + 1):
            if not probs:
                break
            try:
                got = calls.repair(repair_message(bd, d, cont, sc, probs))
            except Exception as exc:
                _logger.warning("breakdown repair failed for %s", sid, exc_info=True)
                notes.append(f"{sid}: the repair call failed ({type(exc).__name__})")
                break
            keep = (sc.brief, sc.blocks)
            build_mod.apply_episode(bd, d, EpisodeW(scenes=[s for s in got.scenes if s.scene == sid]))
            checks.run_all(bd, d)
            now = _blocking(bd, sid)
            if len(now) >= len(probs):  # a worse (or no better) patch is not kept
                sc.brief, sc.blocks = keep
                checks.run_all(bd, d)
                say(f"{sid}: repair {attempt} did not help; the earlier answer stays")
            else:
                say(f"{sid}: repaired ({len(probs)} problem(s) -> {len(now)})")
                probs = now
        if probs:
            notes.append(
                f"{sid}: {len(probs)} problem(s) left after repair: " + "; ".join(p.message for p in probs[:2])
            )
    return notes


def _episodes(
    bd: Breakdown,
    d: Doc,
    cont: dict[str, Any],
    calls: Calls,
    todo: list[list[str]],
    workers: int,
    say: Callable[[str], None],
) -> list[str]:
    notes: list[str] = []

    def one(scene_ids: list[str]) -> tuple[list[str], EpisodeW | None, str]:
        try:
            return (
                scene_ids,
                calls.episode(inputs.episode_user(bd, d, cont, scene_ids, episode_before(bd, d, scene_ids[0]))),
                "",
            )
        except Exception as exc:
            _logger.warning("breakdown episode call failed for %s", scene_ids, exc_info=True)
            return scene_ids, None, type(exc).__name__

    for scene_ids, got, why in _pool(one, todo, workers):
        span = f"{scene_ids[0]}..{scene_ids[-1]}" if len(scene_ids) > 1 else scene_ids[0]
        if got is None:
            notes.append(f"{span}: the breakdown call failed ({why}); these scenes have no breakdown yet")
            continue
        build_mod.apply_episode(bd, d, EpisodeW(scenes=[s for s in got.scenes if s.scene in scene_ids]))
        say(f"Broke down {span}: {len(got.scenes)} scene(s)")
    return notes


def _unbroken(bd: Breakdown) -> list[Finding]:
    return [
        Finding(code="packet", scene=s.id, blocking=True, message="the scene has no breakdown yet")
        for s in bd.scenes
        if s.brief is None
    ]


def read_series(bd: Breakdown, d: Doc, answer: Callable[[], SeriesW], say: Callable[[str], None]) -> list[str]:
    """The series reader's answer, checked by code, onto `bd.series` (plan/2026-11-12b). A failed call or an answer with
    nothing kept leaves `bd.series` None and every prompt as it was; a dropped field is a non-blocking finding.
    -> the notes for a person."""
    try:
        got = answer()
    except Exception as exc:
        _logger.warning("breakdown series call failed", exc_info=True)
        why = type(exc).__name__
        return [f"the drama's genre and tone could not be read ({why}); prompts keep the general wording"]
    block, found = series_mod.check(got, d, bd)
    bd.findings += found
    if not any("says" in (block.get(k) or {}) for k in series_mod.FIELDS):
        return ["the documents do not say the drama's genre or tone; prompts keep the general wording"]
    bd.series = block
    main = series_mod.facets(block)
    say("Read what the drama is" + (f": {', '.join(main)}" if main else ""))
    return []


def create(
    uploads: list[Upload],
    calls: Calls,
    *,
    production: str = "",
    workers: int = WORKERS,
    progress: Callable[[str], None] | None = None,
) -> Result:
    say = progress or (lambda _: None)
    notes: list[str] = []

    def read(u: Upload) -> tuple[Upload, list[str], SplitW | None, str]:
        lines = memory.strip_furniture(memory.clean_lines(u.text))
        try:
            return u, lines, calls.split(split_message(u.filename, Doc(lines))), ""
        except Exception as exc:
            _logger.warning("breakdown split failed for %s", u.filename, exc_info=True)
            return u, lines, None, type(exc).__name__

    sources: list[SourceMemory] = []
    for u, lines, got, why in _pool(read, uploads, workers):
        if got is None:
            notes.append(f"{u.filename} could not be read ({why}); it is left out of the breakdown")
            continue
        sources.append(
            SourceMemory(
                document_id=u.document_id,
                filename=u.filename,
                lines=lines,
                split=got,
                read_from="pages" if u.read_from == "pages" else "text",
            )
        )
        say(f"Read {u.filename}: {len(got.cards)} cards, {sum(len(e.scenes) for e in got.episodes)} scenes")
    if not sources:
        return Result(None, [], "no document could be read", notes)

    split, d, questions = memory.merge(sources)
    bd = memory.stamp(build_mod.build(split, d, production), sources, questions)
    if not bd.scenes:
        notes.append("no scenes were found in the documents")
        return Result(bd, sources, "", notes)
    say(
        f"Built the breakdown: {len(bd.entities)} people, places and things; {len(bd.rules)} direction rules; "
        f"{len(bd.scenes)} scenes"
    )

    # the series reader runs beside the continuity call (plan/2026-11-12b §3.1); it never stops the build
    reading = None
    if calls.series is not None:
        pool = ThreadPoolExecutor(max_workers=1)
        reading = pool.submit(contextvars.copy_context().run, calls.series, series_mod.message(sources))
        pool.shutdown(wait=False)
    try:
        cont = calls.continuity(inputs.continuity_user(bd, d)).model_dump(mode="json")
        say(
            f"Read the story across episodes: {len(cont['timeline'])} scenes in story order, {len(cont['threads'])} "
            "threads"
        )
    except Exception as exc:
        _logger.warning("breakdown continuity call failed", exc_info=True)
        cont = dict(EMPTY_CONTINUITY)
        notes.append(f"the story across episodes could not be read ({type(exc).__name__}): no story order or threads")
    bd.continuity = cont
    if reading is not None:
        notes += read_series(bd, d, reading.result, say)

    notes += _episodes(bd, d, cont, calls, groups(bd), workers, say)
    checks.run_all(bd, d)
    failing = sorted({f.scene for f in bd.findings if f.blocking and f.scene})
    notes += repair(bd, d, cont, calls, failing, say)
    checks.run_all(bd, d)
    bd.findings += _unbroken(bd)
    return Result(bd, sources, "", notes)


def stage_message(bd: Breakdown, scene_id: str) -> str:
    from contracts.breakdown import stage

    sc = bd.scene(scene_id)
    if sc is None or sc.brief is None:
        raise KeyError(f"{scene_id} has no brief")
    return stage.user_message(bd, sc)


# ── after a person edits a scene (plan §4, phase 5) ──────────────────────────────────────────────────────────────


def mark_stale(bd: Breakdown, scene_id: str, script_version: int) -> bool:
    """A scene whose script changed after its brief was built is stale: its packet waits until it is refreshed."""
    sc = bd.scene(scene_id)
    if sc is None or not sc.brief or script_version <= sc.script_version:
        return False
    sc.stale = "a person edited the script after this breakdown was made"
    return True


def refresh_scene(
    bd: Breakdown,
    sources: list[SourceMemory],
    scene_id: str,
    lines: list[str],
    calls: Calls,
    *,
    script_version: int = 0,
    say: Callable[[str], None] = lambda _: None,
) -> list[str]:
    """The one-scene refresh: the person's lines (the heading first) are appended to the memory's own lines, the scene
    is
    pointed at them, the episode call breaks it down again, the checks and repair run, and the stager's map is cleared
    (it is made again before planning). Returns notes; a hand-over the next scene no longer matches is a finding."""
    sc = bd.scene(scene_id)
    if sc is None:
        raise KeyError(scene_id)
    start = len(memory.doc(sources, bd.person_lines)) + 1
    bd.person_lines += [sc.heading, *lines]
    d = memory.doc(sources, bd.person_lines)
    sc.heading_line, sc.first, sc.last = start, start + 1, start + len(lines)
    sc.edited, sc.stage, sc.brief, sc.blocks = True, None, None, []
    cont = bd.continuity or dict(EMPTY_CONTINUITY)
    notes = _episodes(bd, d, cont, calls, [[scene_id]], 1, say)
    checks.run_all(bd, d)
    notes += repair(bd, d, cont, calls, [scene_id] if _blocking(bd, scene_id) else [], say)
    checks.run_all(bd, d)
    bd.findings += [f for f in _unbroken(bd)]
    bd.findings += handover(bd, scene_id)
    if sc.brief is not None:
        sc.stale, sc.script_version = "", script_version or sc.script_version
        bd.version += 1
    return notes


def handover(bd: Breakdown, scene_id: str) -> list[Finding]:
    """Report only: after a refresh, does the next scene in the story still start with what this one now ends with?"""
    order = {t["scene"]: t["story_order"] for t in (bd.continuity or {}).get("timeline", [])}
    ordered = sorted((s for s in bd.scenes if s.brief), key=lambda s: (order.get(s.id, 10**6), bd.scenes.index(s)))
    ids = [s.id for s in ordered]
    if scene_id not in ids or ids.index(scene_id) + 1 >= len(ids):
        return []
    a, b = ordered[ids.index(scene_id)], ordered[ids.index(scene_id) + 1]
    ends = {t["thing"]: t["holder_end"] for t in (a.brief or {}).get("things", []) if t["holder_end"]}
    out = []
    for t in (b.brief or {}).get("things", []):
        if t["thing"] in ends and t["holder_start"] and t["holder_start"] != ends[t["thing"]]:
            out.append(
                Finding(
                    code="continuity",
                    scene=b.id,
                    message=(
                        f"after the edit of {a.id}, {t['thing']} ends it with {ends[t['thing']]} but {b.id} starts "
                        "with "
                        f"{t['holder_start']}: check the hand-over"
                    ),
                )
            )
    return out
