"""Scenes → shot lists. The last hop of the structure build, and the director's "Re-split".

For each scene: script blocks + lines → a planner proposes → the kernel fits → the critic
reviews (one bounded re-plan) → shots written, lines bound to shots and beats, the fit report
stored on the scene. An APPROVED scene is never touched.

Idempotent: a scene's shots are replaced, never appended, and its lines are re-bound in place.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol
from uuid import UUID, uuid4

from contracts import beats as screen_beats
from contracts import bridges, sceneplan, stagemap
from contracts import reading as scene_reading
from contracts.build import Agent, Stage
from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from contracts.production import ProductionSettings
from contracts.sceneplan import fit_report
from contracts.shotplan import FitResult, Item, ProposedShot, allowed_durations, fit
from contracts.veo import SoundMode
from script_split.engine import beats, critic, planner
from script_split.engine import reading as reading_engine
from script_split.engine import staging as staging_engine
from script_split.engine.reading import SceneContext

_logger = logging.getLogger(__name__)
AGENT = Agent.PLANNER.value
PLAN_WORKERS = 4
EPISODE_KEYS = ("total_s", "envelope_s", "silent_s", "off_screen", "need_s")
TIME_BUDGET_S = 420.0  # of the 900 s deadline: a wave of model calls can take minutes


class StoreLike(Protocol):
    def production(self, production_id: UUID) -> dict[str, Any] | None: ...
    def scenes(self, production_id: UUID, scene_ids: list[str] | None) -> list[dict[str, Any]]: ...
    def episodes(self, production_id: UUID) -> list[dict[str, Any]]: ...
    def neighbours(self, production_id: UUID) -> list[dict[str, Any]]: ...
    def lines(self, scene_id: UUID) -> list[dict[str, Any]]: ...
    def characters(self, production_id: UUID) -> list[dict[str, Any]]: ...
    def scene_status(self, production_id: UUID) -> list[dict[str, Any]]: ...
    def replace_shots(self, scene_id: UUID, shots: list[dict[str, Any]], lines: list[dict[str, Any]],
                      scene_fields: dict[str, Any]) -> None: ...
    def set_episode_status(self, episode_id: str, status: str) -> None: ...


class JobsLike(Protocol):
    def check(self, payload: DispatchPayload) -> str | None: ...
    def set(self, job_id: UUID, status: JobStatus, **fields: Any) -> None: ...
    def event(self, job_id: UUID, type_: JobEventType, payload: dict[str, Any], agent: str | None = None) -> None: ...
    def stage(self, job_id: UUID, stage: str, state: str, text: str = "") -> None: ...
    def finish(self, payload: DispatchPayload, result: dict[str, Any],
               next_state: dict[str, Any] | None = None, *, again: bool = False) -> None: ...


class LLMLike(Protocol):
    @property
    def enabled(self) -> bool: ...
    def json(self, *, tier: str, phase: str, system: str, user: str, schema_name: str,
             schema: dict[str, Any]) -> dict[str, Any]: ...


def items_for(scene: dict[str, Any], lines: list[dict[str, Any]]) -> list[Item]:
    return sceneplan.items_for(scene.get("script") or [], lines)


def prepare(scene: dict[str, Any], lines: list[dict[str, Any]], llm: LLMLike,
            cast: list[str] | None = None) -> tuple[list[dict[str, Any]], list[Item]]:
    """→ (the scene's script with its implied steps in and every action block read for this script
    version, the kernel items for it). Blocks that already carry a reading for this version are not
    read again; a person's marks are never replaced."""
    version = int(scene.get("script_version") or 1)
    script = bridges.with_bridges(scene.get("script") or [], lines, version, cast or ())
    items = sceneplan.items_for(script, lines)
    if screen_beats.is_stale(items, version):
        ask = None
        if llm.enabled:
            def ask(system: str, user: str) -> dict[str, Any]:
                return llm.json(tier="medium", phase="script_split.beats", system=system, user=user,
                                schema_name="beat_screen", schema=beats.BEATS_SCHEMA)
        readings, by = beats.classify(ask, items)
        script = screen_beats.annotate(script, lines, readings, version, by)
        items = sceneplan.items_for(script, lines)
    return script, items


def scene_context(scene: dict[str, Any], episodes: dict[str, dict[str, Any]], neighbours: list[dict[str, Any]],
                  cards: list[tuple[str, str]]) -> SceneContext:
    """What surrounds a scene, for the reading and the planner: its episode, the scenes either side in that episode,
    the director's note, the characters' cards."""
    episode = episodes.get(str(scene.get("episode_id"))) or {}
    siblings = sorted((n for n in neighbours if str(n.get("episode_id")) == str(scene.get("episode_id"))),
                      key=lambda n: int(n.get("number") or 0))

    def gist(row: dict[str, Any] | None) -> str:
        if not row:
            return ""
        return " \u2014 ".join(p for p in (str(row.get("heading") or ""), str(row.get("title") or "")) if p)

    number = int(scene.get("number") or 0)
    before = next((n for n in reversed(siblings) if int(n.get("number") or 0) < number), None)
    after = next((n for n in siblings if int(n.get("number") or 0) > number), None)
    return SceneContext(heading=str(scene.get("heading") or ""), note=str(scene.get("note") or ""),
                        episode_title=str(episode.get("title") or ""), synopsis=str(episode.get("synopsis") or ""),
                        before=gist(before), after=gist(after), characters=tuple(cards))


def stage(scene: dict[str, Any], lines: list[dict[str, Any]], script: list[dict[str, Any]], items: list[Item],
          reading: scene_reading.SceneReading, llm: LLMLike, names: dict[str, str], place: str = ""
          ) -> tuple[list[dict[str, Any]], list[Item], scene_reading.SceneReading, stagemap.SceneStaging | None]:
    """Place the scene's people, then walk anyone who would teleport (plan/2026-11-01d, Phase 4).

    -> (the script with its implied moves in, its items, the reading and the map carried across those blocks, the
    map or None). The map comes from one `medium` call (a person's, or one made for these blocks, is kept); CODE finds
    each person who changes zone with nothing to show the way and adds one removable step for each, unless a person
    removed it before. Without a key or without marks there is no map and nothing about places is checked."""
    ask = None
    if llm.enabled:
        def ask(system: str, user: str) -> dict[str, Any]:
            return llm.json(tier="medium", phase="script_split.staging", system=system, user=user,
                            schema_name="scene_staging", schema=staging_engine.STAGING_SCHEMA)
    cast = list(names.values())
    staging, _ = staging_engine.staging_for(scene, items, ask, cast, reading=reading, place=place,
                                            speaker_names=names)
    moves = stagemap.plan_moves(staging, items, cast)
    if staging is None or not moves:
        return script, items, reading, staging
    script, where = bridges.insert_moves(script, lines, moves, int(scene.get("script_version") or 1))
    placed = sceneplan.items_for(script, lines)
    if reading.basis == scene_reading.basis(items):  # a person's out-of-date reading keeps the numbers it had
        reading = scene_reading.remap(reading, placed, where)
    return script, placed, reading, stagemap.remap(staging, placed, where)


def location_notes(store: Any, production_id: UUID) -> dict[str, str]:
    """location id → "Name: what the place is", for the staging map's spots. A store with no locations gives none."""
    rows = getattr(store, "locations", None)
    if rows is None:
        return {}
    return {str(r["id"]): " — ".join(p for p in (str(r.get("name") or ""), str(
        ((r.get("current") or {}).get("card") or {}).get("summary") or "")) if p) for r in rows(production_id)}


def continuity_notes(label: str, scene: dict[str, Any], lines: list[dict[str, Any]]) -> list[str]:
    """Free checks a person should see before directing: a scene with no place, a line nobody
    in the canon speaks, a scene with no script."""
    notes = []
    if not scene.get("location_id"):
        notes.append(f"{label} has no location; frames cannot be matched to a set.")
    unknown = sorted({str(ln["speaker"]) for ln in lines if not ln.get("character_id")})
    if unknown:
        notes.append(f"{label}: {', '.join(unknown)} not linked to a canon character, so no voice pin.")
    if not scene.get("script"):
        notes.append(f"{label} has no script.")
    return notes


def plan_scene(items: list[Item], *, heading: str, envelope_s: int, fixed: int | None, llm: LLMLike,
               speaker_names: dict[str, str], reading: scene_reading.SceneReading | None = None,
               context: SceneContext | None = None, staging: stagemap.SceneStaging | None = None
               ) -> tuple[FitResult, str, list[str]]:
    """-> (fitted plan, which planner, critic notes acted on).

    `items` carry the reading's time (`contracts.reading.apply`). Over the envelope, optional breath is given up
    first (`planner.fold_breath`); the plan, the rules' and the model's, is fitted and scored with what is left, and
    the result says what was given up. Three model critics (coverage, emotion, editor) write notes; the kernel score
    in code, which also weighs the staging map's checks, picks the plan."""
    base = list(items)
    items, rules_shots = planner.rules_plan(base, envelope_s=envelope_s, fixed_seconds=fixed)
    rules = fit(items, rules_shots, envelope_s=envelope_s, fixed_seconds=fixed)

    def finish(result: FitResult, used: str, notes: list[str]) -> tuple[FitResult, str, list[str]]:
        return _with_breath(result, base, items, envelope_s, fixed), used, notes

    if not llm.enabled or not items:
        return finish(rules, "rules", [])
    allowed = allowed_durations(fixed)
    context_text = context.text() if context else ""
    reading_text = reading.text() if reading else ""

    cast = list(speaker_names.values())

    def score(result: FitResult) -> critic.Score:
        return critic.kernel_score(result, reading, items, staging, cast)

    def ask_plan(system: str, user: str) -> dict[str, Any]:
        return llm.json(tier="high", phase="script_split.plan", system=system, user=user,
                        schema_name="shot_plan", schema=planner.PLAN_SCHEMA)

    def ask_critic(lens: str, system: str, user: str) -> dict[str, Any]:
        # The high tier (plan/2026-11-01 fix 11): every later hop inherits this shot list.
        tier = "high" if lens == "coverage" else "medium"  # the two new lenses cost less (plan/2026-11-01d §6)
        return llm.json(tier=tier, phase=f"script_split.critic.{lens}", system=system, user=user,
                        schema_name="shot_review", schema=critic.CRITIC_SCHEMA)

    def plan(notes: list[str] | None = None) -> FitResult:
        proposal = planner.plan_by_model(ask_plan, items, heading=heading, envelope_s=envelope_s, allowed=allowed,
                                         speaker_names=speaker_names, notes=notes, context=context_text,
                                         reading=reading_text)
        return fit(items, proposal, envelope_s=envelope_s, fixed_seconds=fixed)

    try:
        best = plan()
    except Exception:
        _logger.warning("model planner failed; using the rules", exc_info=True)
        return finish(rules, "rules", [])
    notes: list[str] = []
    try:
        found = [f.message for f in stagemap.checks(staging, items, best, cast)]
        notes = critic.review(ask_critic, planner.scene_listing(items, speaker_names), best, items,
                              reading=reading_text, staging=staging.text() if staging else "", found=found)
        if notes:
            revised = plan(notes)
            if score(revised) < score(best):  # a full tie keeps the first plan
                best = revised
    except Exception:
        _logger.warning("critic round failed; keeping the first plan", exc_info=True)
    if score(rules) < score(best):
        return finish(rules, "rules", notes)  # the model's plan broke more than the rules' did
    return finish(best, "model", notes)


def _with_breath(result: FitResult, base: list[Item], kept: list[Item], envelope_s: int,
                 fixed: int | None) -> FitResult:
    """Say what happened to the reading's breath: which holds were given up for the envelope, and what the scene needs
    with all of it and without the optional part ("needs 42 s, 37 s without optional breath")."""
    if not any(i.hold_s > 0 for i in base):
        return result
    result.breath_dropped = [i.index for i in base if i.hold_s > 0 and kept[i.index].hold_s == 0]
    proposal = [ProposedShot(s.start, s.end, s.framing, s.title, s.sound_mode.value, None, False,
                             s.camera_link.value) for s in result.shots]
    core = list(base)
    for held in scene_reading.optional_breath(base):
        core = scene_reading.release(core, held.index)
    full_s = fit(base, proposal, envelope_s=envelope_s, fixed_seconds=fixed).need_s
    core_s = fit(core, proposal, envelope_s=envelope_s, fixed_seconds=fixed).need_s
    result.breath_extra = {
        "dropped": [{"block": i, "seconds": base[i].hold_s, "kind": base[i].hold_kind,
                     "priority": base[i].hold_priority} for i in result.breath_dropped],
        "needs_s": full_s, "core_need_s": core_s}
    return result


Rows = list[dict[str, Any]]


def rows_for(scene: dict[str, Any], result: FitResult, lines: Rows) -> tuple[Rows, Rows]:
    shot_ids = {s.number: str(uuid4()) for s in result.shots}
    shots = [{
        "id": shot_ids[s.number], "production_id": scene["production_id"], "scene_id": scene["id"],
        "number": s.number, "title": s.title, "framing": s.framing, "duration_s": s.duration_s,
        "start_s": s.start_s, "sound_mode": s.sound_mode.value, "camera_link": s.camera_link.value,
        "frame_strategy": s.frame_strategy.value, "speaker_id": s.speaker_id,
        "beats": [{"start_s": b0, "end_s": b1, "camera": "", "director_line": "", "action": ""} for b0, b1 in s.beats],
        "block_start": s.start, "block_end": s.end, "word_target": s.word_target, "words": s.words,
        "status": "draft", "version": 1,
    } for s in result.shots]
    fitted = {fl.line_id: fl for fl in result.lines}
    keep = ("id", "production_id", "scene_id", "ord", "speaker", "character_id", "text", "delivery")
    line_rows = []
    for ln in lines:
        fl = fitted.get(str(ln["id"]))
        row = {k: ln.get(k) for k in keep}
        row.update({"words": fl.words if fl else 0, "shot_id": shot_ids[fl.shot_number] if fl else None,
                    "beat_index": fl.beat_index if fl else None, "start_s": fl.start_s if fl else None,
                    "overrun_s": fl.overrun_s if fl else 0})
        line_rows.append(row)
    return shots, line_rows


def report(result: FitResult, planner_name: str, notes: list[str]) -> dict[str, Any]:
    return fit_report(result, planner_name, notes)


def staging_report(staging: stagemap.SceneStaging, items: list[Item], found: list[stagemap.Finding],
                   cast: list[str]) -> dict[str, Any]:
    """What `fit_report.staging` says: the spots, the problems left (a removed move is one), and the steps added."""
    def rows(code: str) -> list[dict[str, Any]]:
        return [{"message": f.message, "block": f.block, "shot": f.shot, "who": list(f.who), "zone": f.zone}
                for f in found if f.code == code]

    return {"zones": staging.zones, "teleports": rows("teleport"), "line_crossed": rows("line_crossed"),
            "eyeline": rows("eyeline"), "unplaced": stagemap.unplaced(staging, items, cast),
            "moves": [{"block": i.index, "text": i.text} for i in items if bridges.is_move_block(i.bridge)]}


def episode_stats(result: FitResult, scene: dict[str, Any]) -> dict[str, int]:
    """What one scene adds to its episode's line in the build log."""
    off_screen = sum(len(s.line_ids) for s in result.shots if s.sound_mode is SoundMode.VOICEOVER)
    return {"total_s": result.total_s, "envelope_s": int(scene["envelope_s"]), "silent_s": result.silent_s,
            "off_screen": off_screen, "need_s": result.need_s}


def episode_line(number: int, stats: dict[str, int]) -> str:
    """"Episode 1: needs 78 s to show its script; target 60 s, 34 s spoken, 2 lines off screen".

    The first figure is what the script needs on screen, pictures and speech together, not what
    the target squeezed it into: a person decides whether to grow the target or cut a beat."""
    need = max(stats["total_s"], stats.get("need_s", 0))
    first = (f"needs {need} s to show its script; target {stats['envelope_s']} s"
             if need > stats["envelope_s"] else f"{need} s")
    parts = [first, f"{stats['total_s'] - stats['silent_s']} s spoken"]
    if stats["off_screen"]:
        parts.append(f"{stats['off_screen']} line{'s' if stats['off_screen'] != 1 else ''} off screen")
    return f"Episode {number}: " + ", ".join(parts)


def run(payload: DispatchPayload, store: StoreLike, jobs: JobsLike, llm: LLMLike) -> dict[str, Any]:
    skip = jobs.check(payload)
    if skip:
        return {"skipped": skip}
    job_id = payload.job_id
    production_id = payload.production_id
    assert production_id is not None
    jobs.set(job_id, JobStatus.RUNNING)
    production = store.production(production_id)
    if production is None:
        jobs.set(job_id, JobStatus.DONE, result={"skipped": "production deleted"})
        return {"skipped": "production deleted"}
    settings = ProductionSettings.model_validate(production.get("settings") or {})
    fixed = settings.fixed_shot_seconds
    scene_ids = payload.state.get("scene_ids")
    scenes = store.scenes(production_id, [str(s) for s in scene_ids] if scene_ids is not None else None)
    episode_no = {str(e["id"]): int(e["number"]) for e in store.episodes(production_id)}
    characters = store.characters(production_id)
    names = {str(c["id"]): str(c["name"]) for c in characters}
    cards = [(str(c["name"]), str(((c.get("current") or {}).get("card") or {}).get("summary") or ""))
             for c in characters]
    episode_rows = {str(e["id"]): e for e in store.episodes(production_id)}
    neighbours = store.neighbours(production_id)

    # Totals carried from earlier deliveries of this hop (a long build runs in time-boxed batches).
    carried: dict[str, Any] = dict(payload.state.get("progress") or {})
    if not carried:
        jobs.stage(job_id, Stage.SHOTS.value, "active", f"Planning shots for {len(scenes)} scenes")
    started = time.monotonic()
    written = skipped = shot_count = issues = 0
    continuity: list[str] = list(carried.get("continuity") or [])
    episodes: dict[str, dict[str, int]] = {k: dict(v) for k, v in (carried.get("episodes") or {}).items()}
    todo: list[tuple[str, dict[str, Any], list[dict[str, Any]], list[Item]]] = []
    scripts: dict[str, list[dict[str, Any]]] = {}  # scene id → its script with implied steps and readings
    readings: dict[str, scene_reading.SceneReading] = {}  # scene id → its reading (plan/2026-11-01d)
    stagings: dict[str, stagemap.SceneStaging] = {}  # scene id → its staging map (Phase 4)
    staging_reports: dict[str, dict[str, Any]] = {}  # scene id → what the map's checks found
    places = location_notes(store, production_id)
    for scene in scenes:
        label = f"Ep {episode_no.get(str(scene['episode_id']), 0):02d} Scene {scene['number']}"
        if scene["status"] == "approved":
            skipped += 1
            jobs.event(job_id, JobEventType.PROGRESS, {"text": f"{label} is approved; left as it is"}, agent=AGENT)
            continue
        lines = store.lines(UUID(str(scene["id"])))
        if not items_for(scene, lines):
            skipped += 1
            continue
        todo.append((label, scene, lines, []))

    def plan_one(job: tuple[str, dict[str, Any], list[dict[str, Any]], list[Item]]) -> tuple[FitResult, str, list[str]]:
        _, scene, lines, _ = job
        scripts[str(scene["id"])], items = prepare(scene, lines, llm, list(names.values()))
        ask = None
        if llm.enabled:
            def ask(system: str, user: str) -> dict[str, Any]:
                return llm.json(tier="high", phase="script_split.reading", system=system, user=user,
                                schema_name="scene_reading", schema=reading_engine.READING_SCHEMA)
        context = scene_context(scene, episode_rows, neighbours, cards)
        reading, _ = reading_engine.reading_for(scene, items, ask, list(names.values()), context=context,
                                                speaker_names=names)
        script, items, reading, staging = stage(scene, lines, scripts[str(scene["id"])], items, reading, llm, names,
                                                places.get(str(scene.get("location_id")), ""))
        scripts[str(scene["id"])] = script
        reading = scene_reading.clear_envelope(reading)
        timed = scene_reading.apply(items, reading)
        result, used, notes = plan_scene(timed, heading=scene["heading"], envelope_s=int(scene["envelope_s"]),
                                         fixed=fixed, llm=llm, speaker_names=names, reading=reading, context=context,
                                         staging=staging)
        readings[str(scene["id"])] = scene_reading.mark_off(reading, timed, result.breath_dropped)
        if staging is not None:
            stagings[str(scene["id"])] = staging
            found = stagemap.checks(staging, timed, result, list(names.values()))
            staging_reports[str(scene["id"])] = staging_report(staging, timed, found, list(names.values()))
        return result, used, notes

    # Scenes are planned in parallel waves (model calls dominate) and written here, one at a time.
    # Past the time budget, the scenes left go to a fresh delivery of this hop (the function
    # deadline is fixed; a long drama can need more than one).
    workers = PLAN_WORKERS if llm.enabled else 1
    left: list[tuple[str, dict[str, Any], list[dict[str, Any]], list[Item]]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i in range(0, len(todo), workers):
            if i and time.monotonic() - started > TIME_BUDGET_S:
                left = todo[i:]
                break
            wave = todo[i: i + workers]
            for (label, scene, lines, _), (result, used, notes) in zip(wave, pool.map(plan_one, wave), strict=True):
                shots, line_rows = rows_for(scene, result, lines)
                fields: dict[str, Any] = {"status": "split", "fit_report": report(result, used, notes)}
                if str(scene["id"]) in staging_reports:
                    fields["fit_report"]["staging"] = staging_reports[str(scene["id"])]
                if scripts[str(scene["id"])] != (scene.get("script") or []):
                    fields["script"] = scripts[str(scene["id"])]  # implied steps and readings, with the shots
                fields["reading"] = readings[str(scene["id"])].model_dump(mode="json")
                if str(scene["id"]) in stagings:  # no map (no key) leaves a stored one as it is
                    fields["staging"] = stagings[str(scene["id"])].model_dump(mode="json")
                store.replace_shots(UUID(str(scene["id"])), shots, line_rows, fields)
                continuity.extend(continuity_notes(label, scene, lines))
                written += 1
                shot_count += len(shots)
                issues += critic.issue_count(result)
                tally = episodes.setdefault(str(episode_no.get(str(scene["episode_id"]), 0)),
                                            dict.fromkeys(EPISODE_KEYS, 0))
                for key, value in episode_stats(result, scene).items():
                    tally[key] = tally.get(key, 0) + value
                jobs.event(job_id, JobEventType.PROGRESS,
                           {"text": f"{label}: {len(shots)} shots, {result.total_s} s",
                            "scene_id": str(scene["id"]), "shots": len(shots), "total_s": result.total_s,
                            "issues": len(result.issues)}, agent=AGENT)

    totals = {"scenes": written + int(carried.get("scenes", 0)), "skipped": skipped + int(carried.get("skipped", 0)),
              "shots": shot_count + int(carried.get("shots", 0)), "issues": issues + int(carried.get("issues", 0))}
    if left:
        jobs.event(job_id, JobEventType.PROGRESS, {"text": f"{len(left)} scenes left; continuing"}, agent=AGENT)
        jobs.finish(payload, totals, {"build": bool(payload.state.get("build")),
                                      "scene_ids": [str(sc["id"]) for _, sc, _, _ in left],
                                      "progress": {**totals, "continuity": continuity[:50], "episodes": episodes}},
                    again=True)
        return {**totals, "continued": len(left)}
    jobs.stage(job_id, Stage.SHOTS.value, "done", f"{totals['shots']} shots in {totals['scenes']} scenes")

    # Episodes whose scenes all have shots are ready for the Director panel.
    by_episode: dict[str, list[str]] = {}
    for row in store.scene_status(production_id):
        by_episode.setdefault(str(row["episode_id"]), []).append(str(row["status"]))
    for episode_id, statuses in by_episode.items():
        if statuses and all(s in ("split", "approved") for s in statuses):
            store.set_episode_status(episode_id, "approved" if all(s == "approved" for s in statuses) else "ready")

    if payload.state.get("build"):
        for number in sorted(episodes, key=int):
            jobs.event(job_id, JobEventType.AGENT_STEP, {"text": episode_line(int(number), episodes[number])},
                       agent=AGENT)
        jobs.stage(job_id, Stage.CONTINUITY.value, "active")
        for note in continuity[:20]:
            jobs.event(job_id, JobEventType.WARNING, {"text": note}, agent=Agent.CONTINUITY.value)
        jobs.stage(job_id, Stage.CONTINUITY.value, "done",
                   f"{len(continuity)} things to check" if continuity else "No problems found")
        jobs.stage(job_id, Stage.REVIEW.value, "active", "Ready for your review")

    jobs.finish(payload, totals)
    return totals
