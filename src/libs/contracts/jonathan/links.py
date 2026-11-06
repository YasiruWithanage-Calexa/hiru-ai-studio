"""Which scenes carry on from the one before (plan/2026-11-05e §4.3 `jonathan_links`, §7).

    link_of(prev, scene, order, override)   → how `scene` follows `prev`: "continuous", "carry" or ""
    chains(scenes, links)                   → the scenes in the order they are planned: lists that run one after
                                              another; separate lists run at once

`linked` order (D5): a scene is `continuous` when it is in the same episode, in the same place, and its time of day says
it carries on (CONTINUOUS / MOMENTS LATER / SAME TIME); every other pair is unlinked. `episode` order: every
neighbouring pair in an episode is linked; a pair that is not CONTINUOUS is `carry` (looks and what people keep pass
on; place, position and light do not). A person may link or unlink a pair (`override`), and that wins.
A chain never crosses an episode boundary.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from contracts.jonathan.plan import CONTINUOUS_TIMES

Row = Mapping[str, Any]
ORDERS = ("linked", "episode")


def continuous(prev: Row, scene: Row) -> bool:
    """The rule: same episode, same place, and a time of day that carries on."""
    place = str(scene.get("location_id") or "")
    return (str(prev.get("episode_id")) == str(scene.get("episode_id")) and bool(place)
            and place == str(prev.get("location_id") or "")
            and str(scene.get("time_of_day") or "").strip().upper() in CONTINUOUS_TIMES)


def link_of(prev: Row | None, scene: Row, order: str = "linked", override: str | None = None) -> str:
    """"continuous" | "carry" | "" for `scene` after `prev` (the scene before it in the same episode, or None).
    `override`: a person's choice, "continuous", "carry" or "none"."""
    if prev is None or str(prev.get("episode_id")) != str(scene.get("episode_id")):
        return ""
    if override in ("continuous", "carry"):
        return override
    if override == "none":
        return ""
    if continuous(prev, scene):
        return "continuous"
    return "carry" if order == "episode" else ""


def chains(scenes: Sequence[Row], links: Mapping[str, str]) -> list[list[str]]:
    """Scene ids grouped into chains, each in scene order (episode, then number). A scene with no link starts a new
    chain; a linked scene joins the chain of the scene before it."""
    ordered = sorted(scenes, key=lambda s: (int(s.get("episode_number") or 0), str(s.get("episode_id")),
                                            int(s.get("number") or 0)))
    out: list[list[str]] = []
    for s in ordered:
        sid = str(s["id"])
        if links.get(sid) and out:
            out[-1].append(sid)
        else:
            out.append([sid])
    return out
