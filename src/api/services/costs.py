"""A scene's production cost (plan/2026-11-06d §6): what it has cost, plus what it will cost to finish, as ONE figure.

Everything is worked out at read time from metered usage and the dated price list (`contracts.costs` does the money;
this file only gathers rows and decides what is left to do). Nothing here stores a figure, and no breakdown leaves the
server: the router returns `SceneCost` (the total, `designed`, `complete`) and the parts go to a debug log.

  spent      text calls at actual cost + pictures x 1.05 + videos x 1.10, over what the scene's jobs and chat used,
             plus the scene's share of whole-episode work (by its share of the production's dialogue lines, D-A)
  to finish  for each shot without an accepted take: its next video (`video_gen.resolve`, the settings a render would
             use) + a first frame if it has no current accepted one + a prompt if it has no current one;
             frames and prompts at the median of what this production's last ones cost
  total      spent + to finish x 1.20 (the retry margin, to-finish only, D-B)
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any
from uuid import UUID

from api.repositories import Repos, Row
from api.services.renders import shot_state
from contracts import costs
from contracts.costs import Costed, Price, SceneTotal
from contracts.production import ProductionSettings
from contracts.veo import FrameStrategy
from contracts.video_gen import resolve

if TYPE_CHECKING:
    from api.routers.production import Loaded

_logger = logging.getLogger(__name__)

# Whole-episode planning that no single scene made: shared by the scenes by their lines of dialogue. The structure
# build and the shot planners write these before a scene is picked out.
EPISODE_PHASES = ("script_split.", "structure_build.", "adam.", "david.", "jonathan.")
FRAME_PHASE = "frame_render."
FRAME_IMAGE_PHASE = "frame_render.image"
PROMPT_PHASE = "shot_producer.craft"  # one call writes one video prompt
HISTORY_JOBS = 20  # "the last 20 frame_render items"
HISTORY_ROWS = 400


def price_list(rows: Sequence[Mapping[str, Any]]) -> list[Price]:
    """Price rows as the money rules read them. A row that does not parse is skipped and logged, never guessed."""
    out: list[Price] = []
    for r in rows:
        try:
            out.append(Price.model_validate({k: v for k, v in r.items() if k in Price.model_fields}))
        except ValueError:
            _logger.warning("price row %s does not parse; skipped", r.get("id"))
    return out


def per_frame(rows: Sequence[Row], prices: Sequence[Price]) -> int | None:
    """What one first frame cost, from `frame_render.*` rows: each job's cost (pictures and checks, margins in) over the
    pictures it painted; the median of the newest `HISTORY_JOBS` jobs. None without a painted picture."""
    jobs: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        jobs[str(r.get("job_id") or "")].append(r)
    newest = sorted(jobs.values(), key=lambda rs: max(str(r.get("created_at")) for r in rs), reverse=True)
    each: list[int] = []
    for rs in newest[:HISTORY_JOBS]:
        pictures = sum(1 for r in rs if r.get("phase") == FRAME_IMAGE_PHASE)
        if pictures:
            each.append(sum(costs.cost_tokens(r, prices).micros for r in rs) // pictures)
    return costs.median(each)


def per_prompt(rows: Sequence[Row], prices: Sequence[Price]) -> int | None:
    """What one video prompt cost: the median of the newest prompt-writing calls."""
    each = [costs.cost_tokens(r, prices).micros for r in rows[:HISTORY_JOBS]]
    return costs.median(each)


def _shot_needs_frame(st: Any) -> bool:
    if st.row.get("frame_strategy") == FrameStrategy.CARRY_LAST_FRAME:
        return False  # it opens on the previous take's last frame
    return st.accepted is None or bool(st.frame_reasons.get(str(st.accepted["id"])))


def _shot_needs_prompt(st: Any) -> bool:
    return st.prompt is None or bool(st.prompt_reasons)


async def scene_cost(repos: Repos, ld: Loaded, prices_override: Sequence[Price] | None = None) -> SceneTotal:
    """The total for one scene. `ld` is the scene as the Production panel loads it (shots, frames, prompts, ...)."""
    production_id = UUID(str(ld.production["id"]))
    scene_id = UUID(str(ld.scene["id"]))
    shot_ids = [st.id for st in ld.states]

    price_rows, usage, pool, lines, renders, takes = await asyncio.gather(
        repos.costs.prices(), repos.costs.scene_usage(production_id, scene_id),
        repos.costs.unassigned_usage(production_id, EPISODE_PHASES), repos.costs.lines_by_scene(production_id),
        repos.renders.list_for_shots(shot_ids), repos.takes.list_for_shots(shot_ids))
    frame_hist, prompt_hist = await asyncio.gather(
        repos.costs.recent_usage(production_id, FRAME_PHASE, HISTORY_ROWS),
        repos.costs.recent_usage(production_id, PROMPT_PHASE, HISTORY_ROWS))
    # A database before schema v17 has no price table: the prices in code are the same seed it would hold.
    prices = list(prices_override) if prices_override is not None else (price_list(price_rows) or
                                                                         list(costs.SEED_PRICES))

    # ── spent ───────────────────────────────────────────────────────────────────────────────────────
    spent: list[Costed] = []
    parts: dict[str, int] = defaultdict(int)
    for r in usage:
        c = costs.cost_tokens(r, prices)
        spent.append(c)
        parts["frames" if str(r.get("phase", "")).startswith(FRAME_PHASE) else "breakdown"] += c.micros
    total_lines = sum(lines.values())
    mine = lines.get(str(scene_id), 0)
    if pool and total_lines and mine:
        share = costs.Tally().extend(costs.cost_tokens(r, prices) for r in pool)
        shared = share.micros * mine // total_lines
        spent.append(Costed(shared, tuple(share.missing)))
        parts["episode_share"] += shared
    for rd in renders:
        c = costs.cost_render(rd, prices)
        spent.append(c)
        parts["videos"] += c.micros

    # ── to finish ───────────────────────────────────────────────────────────────────────────────────
    finished = {str(t["shot_id"]) for t in takes if t.get("status") == "accepted"}
    video = ProductionSettings.model_validate(ld.production.get("settings") or {}).video
    frame_unit = per_frame(frame_hist, prices)
    prompt_unit = per_prompt(prompt_hist, prices)
    if frame_unit is None:  # nothing made here yet: what frames cost across productions, else the seeded flat price
        frame_unit = per_frame(await repos.costs.recent_usage(None, FRAME_PHASE, HISTORY_ROWS), prices)
    if prompt_unit is None:
        prompt_unit = per_prompt(await repos.costs.recent_usage(None, PROMPT_PHASE, HISTORY_ROWS), prices)
    frame_seed = Costed(frame_unit) if frame_unit is not None else costs.estimate_unit("frame", prices)
    prompt_seed = Costed(prompt_unit) if prompt_unit is not None else costs.estimate_unit("prompt", prices)

    to_finish: list[Costed] = []
    for st in ld.states:
        if st.id in finished:
            continue
        resolved = resolve(video, shot_state(st).settings, None, production_aspect=ld.aspect,
                           shot_seconds=int(st.row["duration_s"]))
        c = costs.estimate_shot_video(resolved, prices)
        to_finish.append(c)
        parts["to_finish_videos"] += c.micros
        if _shot_needs_frame(st):
            to_finish.append(frame_seed)
            parts["to_finish_frames"] += frame_seed.micros
        if _shot_needs_prompt(st):
            to_finish.append(prompt_seed)
            parts["to_finish_prompts"] += prompt_seed.micros

    result = costs.scene_total(spent, to_finish, parts)
    _logger.debug("scene cost scene=%s total=%s spent=%s to_finish=%s complete=%s parts=%s missing=%s",
                  scene_id, result.total_micros, result.spent_micros, result.to_finish_micros, result.complete,
                  dict(result.parts), result.missing)
    return result


def designed(ld: Loaded) -> bool:
    """Every shot has its design ("Recommend settings for all shots" has run). A scene with no shots is not designed."""
    return bool(ld.states) and all(st.has_design for st in ld.states)
