"""The scene state ledger, as Raphael reads it (plan/2026-11-09 phases 3-5). No model, no network.

The map (`contracts.stagemap.SceneStaging`, the stager's one call per scene, saved in `scenes.staging`) is the memory;
everything here is CODE over it, so it costs nothing per turn:

    attach(scene, staging, items, codes)   the scene with the map pinned to its blocks, `opening_state` and each
                                           block's `now` (what changes at it) filled for the listing, capped
    clip_blocks(clip, work)                the blocks a clip plays: its own, else its anchors', else none
    clip_states(scene, work)               clip id -> (the state as it opens, as it ends)
    opens_ends(scene, clip, work)          the same as two short texts, for the report, `read_bin` and the shot

A scene with no map is returned unchanged, byte for byte: the listing, the checks and the prompt read exactly as before.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from contracts import stagemap as sm
from contracts.raphael.bin import Bin
from contracts.raphael.scene import SceneS
from contracts.raphael.wire import Clip
from contracts.shotplan import Item

STATE_LISTING_CHARS = 2400  # the whole addition to the listing, at most (the cached first message)
STATE_TEXT_CHARS = 400  # one clip's opens or ends, at most (ShotIntent.opens / ends)


def _fill(scene: SceneS, staging: sm.SceneStaging, *, props: bool) -> tuple[str, dict[int, str]]:
    items = scene.items()
    order = [i.index for i in items]
    if not order:
        return "", {}
    opening = sm.state_at(staging, items, order[0]).text(props=props)
    now: dict[int, str] = {}
    before = sm.state_at(staging, items, order[0])
    for b in order[1:]:
        after = sm.state_at(staging, items, b)
        said = (
            sm.delta_text(before, after)
            if props
            else sm.delta_text(sm.SceneState(people=before.people), sm.SceneState(people=after.people))
        )
        if said:
            now[b] = said
        before = after
    return opening, now


def _size(opening: str, now: Mapping[int, str]) -> int:
    return len(opening) + sum(len(v) for v in now.values())


def attach(
    scene: SceneS, staging: sm.SceneStaging | None, items: Sequence[Item], codes: Mapping[str, str] | None = None
) -> SceneS:
    """The scene with its map: pinned to the scene's own blocks (`items` are the script's, the same block numbers),
    who is who by code (`codes`: code -> name, the ids the clips' subjects use), the state at the start and what
    changes at each block. The listing addition is capped at `STATE_LISTING_CHARS`: the props in no hand go first, then
    the latest changes. No map, or a map with no marks, gives the scene back unchanged."""
    if staging is None or not staging.marks:
        return scene
    pin = sm.pinned(staging, items, scene.items())
    opening, now = _fill(scene, pin, props=True)
    if _size(opening, now) > STATE_LISTING_CHARS:
        opening, now = _fill(scene, pin, props=False)
    kept: dict[int, str] = {}
    room = STATE_LISTING_CHARS - len(opening)
    for b in sorted(now):
        if len(now[b]) > room:
            break
        kept[b], room = now[b], room - len(now[b])
    blocks = [b.model_copy(update={"now": kept.get(b.index, "")}) for b in scene.blocks]
    known = {k: v for k, v in (codes or {}).items() if k and v}
    return scene.model_copy(
        update={"blocks": blocks, "staging": pin, "codes": known, "opening_state": opening[:STATE_LISTING_CHARS]}
    )


def clip_blocks(clip: Clip, work: Bin | Sequence[Clip] | None = None) -> list[int]:
    """The blocks a clip plays: its own; a stage 2 clip with none plays its anchors' blocks (`work`: the bin, or its
    clips)."""
    if clip.blocks:
        return sorted(set(clip.blocks))
    clips = work.clips if isinstance(work, Bin) else list(work or [])
    by_id = {c.id: c for c in clips}
    out: set[int] = set()
    for a in clip.anchor:
        if a in by_id:
            out.update(by_id[a].blocks)
    return sorted(out)


def story_of(
    clip: Clip, moments: Mapping[int, tuple[str, str]], long: Mapping[int, float], clips: Sequence[Clip]
) -> tuple[str, str]:
    """-> (what happens in the clip, what the audience should feel): its moment's `what` and `feeling`; a must clip over
    an action longer than any take says which part of it it shows."""
    what, feeling = moments.get(clip.moment, ("", ""))
    for b in sorted(set(clip.blocks) & set(long)):
        over = sorted((c for c in clips if c.priority == "must" and b in c.blocks), key=lambda c: c.id)
        if clip.priority == "must" and len(over) > 1:
            part = [c.id for c in over].index(clip.id) + 1
            what = f"{what} (part {part} of {len(over)} of b{b})".strip()
    return what[:300], feeling[:200]


def states_of(
    staging: sm.SceneStaging | None, items: Sequence[Item], blocks: Sequence[int]
) -> tuple[sm.SceneState, sm.SceneState]:
    """The state as a clip over `blocks` opens and as it ends; with no block at all, nothing."""
    return sm.clip_state(staging, items, blocks)


def clip_states(scene: SceneS, work: Bin) -> dict[str, tuple[sm.SceneState, sm.SceneState]]:
    """Clip id -> (opens, ends) for every clip of the bin, from the scene's ledger. {} with no ledger."""
    if scene.staging is None:
        return {}
    items = scene.items()
    return {c.id: states_of(scene.staging, items, clip_blocks(c, work)) for c in work.clips}


def opens_ends(scene: SceneS, clip: Clip, work: Bin | None = None) -> tuple[str, str]:
    """A clip's opening and closing state as text ("", "" with no ledger)."""
    if scene.staging is None:
        return "", ""
    opens, ends = states_of(scene.staging, scene.items(), clip_blocks(clip, work))
    return opens.text()[:STATE_TEXT_CHARS], ends.text()[:STATE_TEXT_CHARS]
