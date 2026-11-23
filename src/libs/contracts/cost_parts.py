"""Setup apart from scene cost (plan/2026-11-23b): which part of the spend a `token_usage` row is, and where it is
charged.

    production setup   canon (extract, refine, the breakdown's canon / looks / series passes), character and look
                       sheets, questions about the production: charged to the production (a sheet is painted once, every
                       episode uses it)
    episode setup      reading the episode's document, its breakdown, script split, structure build, ALL of Shot
                       Planner Raphael (the upload-time plan and every re-plan; the person, 2026-11-23): charged to the
                       episode, as dated entries (upload, each re-plan, each re-read)
    scene              shot design, Camera, prompts, first frames and boards, video, chat (Zora, Sable, the director
                       chat): charged to the scene ("Scene ≈ $X")

Pure: rows, jobs, scenes, episodes and prices go in; final micro-dollars come out (`contracts.costs`, margins in). The
part is decided by the row's phase, with the job deciding the two cases a phase cannot: canon refine runs the
breakdown's agents, and a character or look sheet is painted under the first frames' phase.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from contracts import costs
from contracts.costs import Price

Part = Literal["production_setup", "episode_setup", "scene"]
PARTS: tuple[Part, ...] = ("production_setup", "episode_setup", "scene")

# The closed table, by the phase's first segments. A phase that matches none is production setup (never dropped), and
# `tests/contracts/test_cost_parts.py` fails on any declared phase this table does not name.
PRODUCTION_SETUP_PHASES: tuple[str, ...] = ("canon_extract", "breakdown.canon", "breakdown.looks", "breakdown.series",
                                            "search")
EPISODE_SETUP_PHASES: tuple[str, ...] = ("doc_ingest", "breakdown", "script_split", "structure_build", "raphael",
                                         "adam", "david", "jonathan")
SCENE_PHASES: tuple[str, ...] = ("director", "zora", "sable", "shot_producer", "camera_agent", "shot_prompter",
                                 "frame_render", "video_render")
# Jobs whose every row is production setup, whatever agent wrote it (canon refine runs the breakdown's agents).
PRODUCTION_SETUP_JOBS: frozenset[str] = frozenset({"canon_extract", "canon_refine"})
# A frame_render job painting a sheet names what it is for (`routers/canon.py`, `routers/looks.py`).
CHARACTER_SHEET_KEY = "entity_id"
LOOK_SHEET_KEY = "look_id"
REPLAN_JOBS: Mapping[str, str] = {"plan_scene_raphael": "Re-plan", "cinematic_scene_raphael": "More cinematic"}
READ_JOB = "doc_ingest"


def _names(phase: str, names: Iterable[str]) -> bool:
    return any(phase == n or phase.startswith(n + ".") for n in names)


def known_phase(phase: str) -> bool:
    return _names(phase, PRODUCTION_SETUP_PHASES + EPISODE_SETUP_PHASES + SCENE_PHASES)


def _request(job: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return (job or {}).get("request") or {}


def sheet_kind(job: Mapping[str, Any] | None) -> Literal["character", "look"] | None:
    request = _request(job)
    if (job or {}).get("kind") != "frame_render":
        return None
    if request.get(LOOK_SHEET_KEY):
        return "look"
    if request.get(CHARACTER_SHEET_KEY):
        return "character"
    return None


def part_of(phase: str, job: Mapping[str, Any] | None) -> Part:
    """The part of one row. The job decides first (canon jobs, sheet paintings), then the phase."""
    if (job or {}).get("kind") in PRODUCTION_SETUP_JOBS:
        return "production_setup"
    if phase.startswith("frame_render") and sheet_kind(job):
        return "production_setup"
    if _names(phase, PRODUCTION_SETUP_PHASES):  # before episode setup: `breakdown.canon` is inside `breakdown`
        return "production_setup"
    if _names(phase, EPISODE_SETUP_PHASES):
        return "episode_setup"
    if _names(phase, SCENE_PHASES):
        return "scene"
    return "production_setup"


# ── which episode a setup row is charged to ───────────────────────────────────────────────────────────────────

ALL_EPISODES: tuple[str, ...] = ()  # shared across every episode of the production by its dialogue lines


def episodes_of(row: Mapping[str, Any], job: Mapping[str, Any] | None, scene_episode: Mapping[str, str],
                document_episodes: Mapping[str, Sequence[str]]) -> tuple[str, ...]:
    """The episode(s) an episode-setup row is charged to; `ALL_EPISODES` = shared by lines. First that answers:
    the row's scene, its job's scene, the episode(s) built from its job's document."""
    for scene_id in (row.get("scene_id"), _request(job).get("scene_id")):
        episode = scene_episode.get(str(scene_id)) if scene_id else None
        if episode:
            return (episode,)
    document = _request(job).get("document_id")
    if document:
        return tuple(document_episodes.get(str(document), ()))
    return ALL_EPISODES


def document_episodes(episodes: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    """document id -> the episodes built from it (`episodes.source_document_ids`)."""
    out: dict[str, list[str]] = {}
    for ep in episodes:
        for doc in ep.get("source_document_ids") or []:
            out.setdefault(str(doc), []).append(str(ep["id"]))
    return out


def share(micros: int, among: Sequence[str], lines: Mapping[str, int]) -> dict[str, int]:
    """`micros` split among episodes by their dialogue lines (equally when none has any). The remainder goes to the
    first, so the parts always add up to the whole."""
    if not among:
        return {}
    weights = [max(int(lines.get(e, 0)), 0) for e in among]
    if not sum(weights):
        weights = [1] * len(among)
    total = sum(weights)
    parts = {e: micros * w // total for e, w in zip(among, weights, strict=True)}
    parts[among[0]] += micros - sum(parts.values())
    return parts


# ── the setup figures ─────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Entry:
    """One line of a setup figure: what it was, when, and its final price."""

    label: str
    at: str  # the earliest row's time (ISO)
    micros: int = 0
    missing: list[str] = field(default_factory=list)

    def add(self, priced: costs.Costed, at: str) -> None:
        self.micros += priced.micros
        self.at = min(self.at, at)
        for note in priced.missing:
            if note not in self.missing:
                self.missing.append(note)


@dataclass
class Setup:
    entries: list[Entry] = field(default_factory=list)

    @property
    def micros(self) -> int:
        return sum(e.micros for e in self.entries)

    @property
    def complete(self) -> bool:
        return not any(e.missing for e in self.entries)


@dataclass
class SetupFigures:
    production: Setup
    episodes: dict[str, Setup]  # episode id -> its setup (every episode of the production, empty ones too)


PRODUCTION_LABELS: Mapping[str, str] = {
    "canon": "Canon", "canon_refine": "Canon refine", "character": "Character sheets", "look": "Look sheets",
    "questions": "Questions about the production", "no_episode": "Not yet in an episode",
}
UPLOAD_LABEL = "Upload and first plan"
SHARED_LABEL = "Production build, shared by lines"
REREAD_LABEL = "Document read again"


def _production_key(phase: str, job: Mapping[str, Any] | None) -> str:
    kind = (job or {}).get("kind")
    if kind == "canon_refine":
        return "canon_refine"
    sheet = sheet_kind(job) if phase.startswith("frame_render") else None
    if sheet:
        return sheet
    if _names(phase, ("search",)):
        return "questions"
    return "canon"


def _at(row: Mapping[str, Any]) -> str:
    value = row.get("created_at")
    return value.isoformat() if isinstance(value, datetime) else str(value or "")


def setup_figures(rows: Iterable[Mapping[str, Any]], jobs: Mapping[str, Mapping[str, Any]],
                  scenes: Iterable[Mapping[str, Any]], episodes: Sequence[Mapping[str, Any]],
                  lines_by_scene: Mapping[str, int], prices: Sequence[Price]) -> SetupFigures:
    """Every setup row of a production priced (final) and charged: production entries by kind, episode entries by
    event (the upload, each re-plan, each re-read), shared build work split by dialogue lines."""
    scene_rows = list(scenes)
    scene_episode = {str(s["id"]): str(s["episode_id"]) for s in scene_rows if s.get("episode_id")}
    scene_number = {str(s["id"]): s.get("number") for s in scene_rows}
    episode_ids = [str(e["id"]) for e in episodes]
    lines: dict[str, int] = {}
    for sid, n in lines_by_scene.items():
        ep = scene_episode.get(str(sid))
        if ep:
            lines[ep] = lines.get(ep, 0) + int(n)
    by_doc = document_episodes(episodes)
    first_read: dict[str, str] = {}  # document -> its first doc_ingest job (by time)
    for jid, read in sorted(jobs.items(), key=lambda kv: str(kv[1].get("created_at") or "")):
        doc = _request(read).get("document_id")
        if read.get("kind") == READ_JOB and doc:
            first_read.setdefault(str(doc), jid)

    production: dict[str, Entry] = {}
    per_episode: dict[str, dict[str, Entry]] = {e: {} for e in episode_ids}
    shared: dict[str, Entry] = {}

    def entry(book: dict[str, Entry], key: str, label: str, at: str) -> Entry:
        return book.setdefault(key, Entry(label, at))

    for r in rows:
        job_id = str(r.get("job_id") or "")
        job = jobs.get(job_id)
        phase = str(r.get("phase") or "")
        part = part_of(phase, job)
        if part == "scene":
            continue
        priced = costs.cost_tokens(r, prices)
        if not priced.micros and not priced.missing:  # a video meter row: priced from its render, which is scene work
            continue
        at = _at(r)
        if part == "production_setup":
            key = _production_key(phase, job)
            entry(production, key, PRODUCTION_LABELS[key], at).add(priced, at)
            continue
        if not episode_ids:
            entry(production, "no_episode", PRODUCTION_LABELS["no_episode"], at).add(priced, at)
            continue
        key, label = _episode_event(job_id, job, scene_number, first_read)
        targets = episodes_of(r, job, scene_episode, by_doc)
        if targets == ALL_EPISODES:
            entry(shared, key, SHARED_LABEL if key == "upload" else label, at).add(priced, at)
            continue
        for ep, part_micros in share(priced.micros, list(targets), lines).items():
            entry(per_episode.setdefault(ep, {}), key, label, at).add(costs.Costed(part_micros, priced.missing), at)

    # shared build work: each event split among every episode by lines, as its own entry
    for key, whole in shared.items():
        for ep, part_micros in share(whole.micros, episode_ids, lines).items():
            label = whole.label if key == "upload" else f"{whole.label} (shared)"
            entry(per_episode[ep], f"shared:{key}", label, whole.at).add(
                costs.Costed(part_micros, tuple(whole.missing)), whole.at)

    def ordered(book: dict[str, Entry]) -> list[Entry]:
        return sorted(book.values(), key=lambda e: (e.at, e.label))

    return SetupFigures(production=Setup(ordered(production)),
                        episodes={ep: Setup(ordered(book)) for ep, book in per_episode.items()})


def _episode_event(job_id: str, job: Mapping[str, Any] | None, scene_number: Mapping[str, Any],
                   first_read: Mapping[str, str]) -> tuple[str, str]:
    """(entry key, label) of an episode-setup row: a re-plan, a re-read, or the upload."""
    kind = str((job or {}).get("kind") or "")
    request = _request(job)
    if kind in REPLAN_JOBS and request.get("scene_id"):
        number = scene_number.get(str(request["scene_id"]))
        where = f", scene {number}" if number is not None else ""
        return f"replan:{job_id}", f"{REPLAN_JOBS[kind]}{where}"
    doc = request.get("document_id")
    if kind == READ_JOB and doc and first_read.get(str(doc)) != job_id:
        return f"reread:{job_id}", REREAD_LABEL
    return "upload", UPLOAD_LABEL


# ── a month by purpose (Settings → Usage) ─────────────────────────────────────────────────────────────────────


@dataclass
class PurposeTotals:
    production_setup: int = 0
    episode_setup: int = 0
    scene: int = 0

    def add(self, part: Part, micros: int) -> None:
        setattr(self, part, getattr(self, part) + micros)

    @property
    def total(self) -> int:
        return self.production_setup + self.episode_setup + self.scene


__all__ = [
    "ALL_EPISODES",
    "PARTS",
    "Entry",
    "Part",
    "PurposeTotals",
    "Setup",
    "SetupFigures",
    "document_episodes",
    "episodes_of",
    "known_phase",
    "part_of",
    "setup_figures",
    "share",
    "sheet_kind",
]
