"""The Camera agent's one door (plan/2026-11-20c D3, D10, D11): brief, ask, check, repair once, merge.

    on()                                         a model to call (no switch: the camera agent always designs)
    design(ctx, scene, prod, ...)                -> Designed: a new design row per clip it was asked for

Called from four places (D11): Shot Planner Raphael after its write (every clip of a planned scene), the Zora/Sable row
kernel (the clips a turn added or changed, one call with the scene as context), "Recommend settings for all shots"
(the scene again) and "Ask Camera" (one shot, with the person's note). A person's field change (`PATCH .../camera`)
makes no call.

ONE call per scene (every clip in cut order) or per one-shot ask; ONE repair with the faults (the whole answer); a clip
still faulty after it keeps the rule recommendation, marked "not designed" with its faults, and the caller adds a
WARNING; the rest of the scene keeps the agent's design (D10). No key: no call, the rule camera stands.

`scene` and its shots are the `serialize` step's `SceneInput` / `ShotInput`; the facts, the brief, the gates and the
merge are the `camera_design` step's (pure); the knowledge base's ideas come from the `search` port's embedding
search (absent-safe).
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from hiru_ai.core import agents, llm, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.settings import get_settings

_log = logging.getLogger(__name__)
Row = dict[str, Any]
AGENT = "camera_agent"
MAX_OUTPUT = 16000  # D2: the runs used ~6-7k output tokens a scene
NEEDS_MODEL = "the Camera agent needs a model: the camera stays as the rules made it"
LOCKED = re.compile(r"locked[- ]off", re.I)


@dataclass
class Designed:
    designs: dict[str, Row] = field(default_factory=dict)  # shot id -> its new design row (only the clips asked for)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # the gates' advisories, for a log
    language: str = ""
    repaired: bool = False
    fallback: list[str] = field(default_factory=list)  # shot codes that kept the rule camera (D10)

    @property
    def designed(self) -> int:
        return len(self.designs) - len(self.fallback)


def on() -> bool:
    return llm.models_enabled()


def model_name() -> str:
    return str(get_settings().openai.model_camera_agent)


def packet_of(ctx: RunContext, scene_row: Row) -> Row | None:
    """The scene's breakdown packet when a planner may read it (the video prompt step's rule), else None: the brief
    then tells the scene from its own rows. Absent-safe."""
    breakdown = getattr(ctx.ports, "breakdown", None)
    if breakdown is None:
        return None
    try:
        packet, _ = parts.step("video_prompt", "facts").usable_packet(breakdown, scene_row)
    except Exception:  # a broken store: the scene's own rows
        _log.warning("the scene packet could not be read for the Camera agent", exc_info=True)
        return None
    return dict(packet) if isinstance(packet, Mapping) else None


def _mood(packet: Mapping[str, Any] | None) -> str:
    feeling = (packet or {}).get("F_feeling")
    return " ".join(str(m) for m in (feeling or {}).get("mood") or []) if isinstance(feeling, Mapping) else ""


def _ideas(ctx: RunContext, clips: Sequence[Row], wanted: set[str]) -> dict[str, list[tuple[str, str]]]:
    """slate -> the knowledge base's ideas for the clip (D8): one embedding call for every query, then the search, k=4.
    Absent-safe: no search port, no key or any failure -> no ideas."""
    kb = parts.step("camera_design", "kb")
    search = getattr(ctx.ports, "search", None)
    asked = [c for c in clips if str(c["slate"]) in wanted and kb.query(c)]
    if search is None or not asked:
        return {}
    try:
        from hiru_ai.rag.embeddings import embed_texts

        vectors = embed_texts([kb.query(c) for c in asked], "camera_agent.ideas", ctx.sink())
        out: dict[str, list[tuple[str, str]]] = {}
        for c, vec in zip(asked, vectors, strict=True):
            rows = search.techniques(kb.query(c), vec, 4)
            out[str(c["slate"])] = kb.ideas(rows or [], kb.fits(c))
        return out
    except Exception:  # an idea is a nicety: the menu still goes
        _log.warning("the knowledge base's ideas could not be read; the Camera agent gets the menu only", exc_info=True)
        return {}


def design(ctx: RunContext, scene: Any, prod: Any, *, packet: Row | None = None,
           line_rows: list[Row] | None = None, focus: Sequence[str] | None = None, note: str = "",
           job_id: str = "") -> Designed:
    """A new design row for each clip asked for (`focus`: shot ids; None = every clip of the scene). Each row is the
    shot's stored design with `recommended` and `camera` replaced (D5); its pins and the rest are kept. The caller
    saves the rows and reports `warnings`."""
    out = Designed()
    if not on():
        out.warnings.append(NEEDS_MODEL)
        return out
    facts = parts.step("camera_design", "facts")
    brief = parts.step("camera_design", "brief")
    gates = parts.step("camera_design", "gates")
    merge = parts.step("camera_design", "merge")
    shots = sorted(scene.shots, key=lambda s: s.number)
    if not shots:
        return out
    lids = facts.lids_of(scene, packet, list(line_rows or []))
    mood = _mood(packet)
    clips = [facts.clip_facts(s, scene, lids, mood=mood) for s in shots]
    by_id = {s.id: (s, c) for s, c in zip(shots, clips, strict=True)}
    one_shot = focus is not None and set(focus) != {s.id for s in shots}
    asked_ids = [s.id for s in shots if focus is None or s.id in set(focus)]
    if not asked_ids:
        return out
    slates = [str(by_id[i][1]["slate"]) for i in asked_ids]
    language = merge.language_of([s.row.get("design") for s in shots])
    scene_text = facts.scene_text(scene, packet, prod)
    locked = bool(LOCKED.search(scene_text))  # lab/camera_moves `locked_direction`: the production's own direction
    inp: Row = {"scene": brief.scene_part(scene_text),
                "clips": brief.clips_part(clips, _ideas(ctx, clips, set(slates)))}
    if one_shot:
        inp.update(focus=slates, current=brief.current_part(clips), language=language, note=" ".join(note.split()))
    agent = agents.build(AGENT)
    focus_slates = slates if one_shot else []
    answer: Row | None = None
    faults: list[str] = []
    try:
        answer = agent.run(inp, ctx, max_output=MAX_OUTPUT).model_dump(mode="json")
        faults, notes = gates.check_scene(answer, clips, focus=focus_slates, locked=locked)
        if faults:  # D10: ONE repair, shown its first answer and exactly what code found
            out.repaired = True
            first = json.dumps(answer, ensure_ascii=False)
            answer = agent.run({**inp, "repair": faults, "previous": first}, ctx,
                               max_output=MAX_OUTPUT).model_dump(mode="json")
            faults, notes = gates.check_scene(answer, clips, focus=focus_slates, locked=locked)
        out.notes = notes
    except Exception:  # the model failed or is down: the rule camera stands, and the job says so
        _log.warning("the Camera agent failed for scene %s", getattr(scene, "id", "?"), exc_info=True)
        faults = ["the model call failed"]
        answer = None
    language = str((answer or {}).get("camera_language") or language) if not one_shot else (language or str(
        (answer or {}).get("camera_language") or ""))
    out.language = language
    stored = next(((s.row.get("design") or {}).get("camera") or {} for s in shots
                   if isinstance((s.row.get("design") or {}).get("camera"), Mapping)), {})
    arc = str((answer or {}).get("arc") or "") if not one_shot else str(stored.get("arc") or "")
    peak = str((answer or {}).get("peak_slate") or "") if not one_shot else str(stored.get("peak_slate") or "")
    answered = {str(c.get("slate")): c for c in (answer or {}).get("clips") or [] if isinstance(c, Mapping)}
    named = gates.faulty_slates(faults, slates)
    unnamed = [f for f in faults if f.split(":", 1)[0].strip() not in set(slates)]
    for sid in asked_ids:
        shot, clip = by_id[sid]
        slate = str(clip["slate"])
        mine = [f for f in faults if f.split(":", 1)[0].strip() == slate]
        c = answered.get(slate)
        failed = answer is None or c is None or slate in named
        if failed and not mine:
            mine = [f for f in unnamed if f.startswith(("the model", "answer slates"))] or ["no answer for this clip"]
        base = shot.recommended(scene)
        out.designs[sid] = merge.merged(dict(shot.row.get("design") or {}), None if failed else c, base=base,
                                        language=language, model=model_name(), job_id=job_id,
                                        faults=mine if failed else [], arc=arc, peak=peak)
        if failed:
            out.fallback.append(shot.code)
    if out.fallback:
        out.warnings.append(f"Scene {scene.number}: the Camera agent could not design {', '.join(out.fallback)}; the "
                            "rule camera stands there: " + "; ".join(faults)[:300])
    scene_wide = [f for f in unnamed if f.startswith("scene:")]
    if scene_wide and answer is not None:
        out.warnings.append(f"Scene {scene.number}: the camera is designed, with " + "; ".join(scene_wide)[:300])
    return out
