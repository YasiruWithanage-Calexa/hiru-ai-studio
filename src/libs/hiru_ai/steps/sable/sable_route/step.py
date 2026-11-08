"""sable_route: which tier a Sable turn starts on (plan/2026-11-08 §4.4 step 1). Code only, free, before the first call.

A small CLOSED list of rules, each with a name, so a turn's record says why it started deep and the lab can drop a rule
that does not pay. A model classifier is rejected on purpose (it adds a call and its latency to every turn).

    run({"message", "attachments": 0}) -> {"tier": "sable" | "sable_deep", "rule": "" | <the rule that fired>}
"""
from __future__ import annotations

import re
from typing import Any

BASE, DEEP = "sable", "sable_deep"
LONG_WORDS = 600  # a message above this many words starts deep
MANY_SCENES = 3  # naming this many different scenes starts deep

# The person asked for depth: compare, review a whole thing, think carefully, plan. Whole words, any case.
DEPTH = re.compile(r"\b(think (it through|carefully|hard(er)?)|carefully|in depth|compare|comparison|contrast|"
                   r"review (the )?(whole|entire|all)|go through (the )?(whole|entire|all)|"
                   r"plan (out|the|a|for)|step by step|pros and cons|trade-?offs?)\b", re.IGNORECASE)
WHOLE_EPISODE = re.compile(r"\b(whole|entire|all of|every scene (of|in)|all (the )?scenes (of|in))\s+(the\s+)?"
                           r"(episode|ep\.?)\s*\d*", re.IGNORECASE)
SCENE = re.compile(r"\b[Ee]\s*(\d+)\s*[Ss]\s*(\d+)\b")

# (name, test) in the order they are tried; the first that holds names the reason.
RULES: tuple[tuple[str, Any], ...] = (
    ("attachment", lambda m, n: n > 0),
    ("long_message", lambda m, n: len(m.split()) > LONG_WORDS),
    ("asked_for_depth", lambda m, n: DEPTH.search(m) is not None),
    ("whole_episode", lambda m, n: WHOLE_EPISODE.search(m) is not None),
    ("many_scenes", lambda m, n: len({(int(e), int(s)) for e, s in SCENE.findall(m)}) >= MANY_SCENES),
)


def route(message: str, attachments: int = 0) -> tuple[str, str]:
    """-> (tier, rule): the deep tier and the first rule that holds, or the base tier and ""."""
    for name, test in RULES:
        if test(message or "", int(attachments or 0)):
            return DEEP, name
    return BASE, ""


def run(payload: dict[str, Any]) -> dict[str, Any]:
    tier, rule = route(str(payload.get("message") or ""), int(payload.get("attachments") or 0))
    return {"tier": tier, "rule": rule}
