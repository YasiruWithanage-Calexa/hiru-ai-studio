"""The cinematography knowledge base (src/libs/hiru_ai/knowledge_bases/cinematography/sources, 629 terms) as the
Camera agent's toolbox: A) the MENU, one line per move in the agent's catalogue with what it does and when to use it;
B) IDEAS, a short list per clip found by keyword search over the terms' tags, effect and use case (free, no Supabase,
no embeddings). Read from the CSVs; nothing is written.

Caveats kept from the read: `is_ai_supported` is a generic guess (crane 0, boom 1), not Omni; tags are noisy; the
static/locked-off term lists "Dialogue scenes" first, so it is never offered as an idea (the agent still has `hold`).
"""
from __future__ import annotations

import csv
import re
from functools import cache
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "libs" / "hiru_ai" / "knowledge_bases" / "cinematography" / "sources"

# the agent's move -> the knowledge base's term ("" = not in the base: written here)
MOVE_TERM: dict[str, str] = {
    "hold": "static_locked_off_shot", "breathing": "", "drift": "", "reframe": "", "push_in": "dolly",
    "slow_creep": "push_in_creep_in", "pull_out": "pull_out", "push_then_hold": "", "pull_back_reveal": "reveal_shot",
    "push_past_foreground": "", "truck_left": "truck", "truck_right": "truck", "tracking_alongside": "crab_shot",
    "lead": "tracking_shot", "follow": "tracking_shot", "track_then_hold": "", "arc_left": "arc_shot",
    "arc_right": "arc_shot", "half_orbit": "orbit_shot", "orbit": "orbit_shot", "circle_two": "circle_track_shot",
    "pan_left": "pan", "pan_right": "pan", "follow_pan": "pan", "whip_pan": "whip_pan", "slow_pan_reveal": "pan",
    "tilt_up": "tilt", "tilt_down": "tilt", "tilt_reveal": "low_to_high_high_to_low_reveal", "dutch_roll": "roll",
    "pedestal_up": "pedestal", "pedestal_down": "pedestal", "crane_up": "boom_shot", "crane_down": "boom_shot",
    "rising_reveal": "boom_up_boom_down", "zoom_in": "zoom", "zoom_out": "zoom", "slow_zoom": "zoom",
    "snap_zoom": "zoom", "crash_zoom": "zoom", "dolly_zoom": "dolly_zoom", "aerial_establishing": "aerial_drone_shot",
    "aerial_reveal": "aerial_drone_shot", "aerial_pull_away": "aerial_drone_shot", "top_down": "overhead_top_down_shot",
    "flyover": "aerial_drone_shot", "whip_out": "whip_pan", "whip_in": "whip_pan", "focus_out": "bokeh_transition",
    "focus_in": "bokeh_transition", "shake": "handheld",
}
FOCUS_TERM = {"rack_focus": "rack_focus_pull_focus", "focus_follow": "follow_focus_2",
              "shallow_isolation": "shallow_focus", "deep": "deep_focus"}
OWN: dict[str, str] = {  # moves the base has no row for: what they do, when to use them
    "breathing": "the frame floats and sways a little all the time, as on an operator's shoulder. Use: the default "
                 "life of dialogue coverage; the audience feels a person behind the camera.",
    "drift": "a slow sideways or forward float of a few inches. Use: a listener, a reaction, a detail that needs life "
             "without a statement.",
    "reframe": "a small pan/tilt correction as people shift. Use: when someone moves inside the shot.",
    "push_then_hold": "a push that lands and stays. Use: a line or realisation that must land, then sit.",
    "track_then_hold": "travel with a person, then stop as they stop. Use: arrivals, a walk that ends in a meeting.",
    "push_past_foreground": "move through a foreground object (a doorway, a shoulder, leaves) toward the subject. "
                            "Use: entering a private moment, discovery.",
}
VARIANT = {"pull_back_reveal": "pulling back", "lead": "moving ahead of the person, backward", "follow": "behind them",
           "tracking_alongside": "beside them", "half_orbit": "half a circle", "crane_up": "rising",
           "crane_down": "descending", "slow_zoom": "slow, almost a creep", "snap_zoom": "fast", "crash_zoom": "fast, "
           "violent", "whip_out": "first half of a whip transition", "whip_in": "second half", "follow_pan": "turning "
           "with a moving person", "slow_pan_reveal": "slow, discovering", "aerial_pull_away": "pulling away and up",
           "focus_out": "defocus out (transition)", "focus_in": "focus in (transition)", "shake": "impact shake"}
STOP = set("a an the and or of to in on at for with by from as is are be it its this that their his her them they "
           "she he into over than then so not no very more most one two who what when where while just only".split())


def _read(name: str) -> list[dict[str, str]]:
    with (SRC / name).open(encoding="utf-8", newline="") as fh:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)]


@cache
def terms() -> dict[str, dict[str, str]]:
    tags = {t["tag_id"]: t["tag_slug"] for t in _read("tags.csv")}
    by_term: dict[str, list[str]] = {}
    for x in _read("term_tags.csv"):
        by_term.setdefault(x["term_id"], []).append(tags[x["tag_id"]])
    out = {}
    for t in _read("cine_terms.csv"):
        t["tags"] = " ".join(by_term.get(t["term_id"], []))
        out[t["term_slug"]] = t
    return out


def menu(moves: list[str]) -> str:
    """One line per move: what it does to the viewer and when to use it (from the base, or OWN)."""
    out = ["<moves>", "Your whole toolbox, from Hiru's cinematography knowledge base. Consider all of it, pick what the "
           "moment needs. Format: move: what it does. Use: when."]
    for m in moves:
        term = terms().get(MOVE_TERM.get(m, ""))
        if term:
            v = f" ({VARIANT[m]})" if m in VARIANT else ""
            out.append(f"- {m}{v}: {term['effect'].rstrip('.')}. Use: {term['use_case'].rstrip('.')}.")
        elif m in OWN:
            out.append(f"- {m}: {OWN[m]}")
        else:
            out.append(f"- {m}")
    out.append("Focus:")
    for f, slug in FOCUS_TERM.items():
        t = terms()[slug]
        out.append(f"- {f}: {t['effect'].rstrip('.')}. Use: {t['use_case'].rstrip('.')}.")
    out.append("</moves>")
    return "\n".join(out)


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if w not in STOP and len(w) > 2}


def stem(w: str) -> str:
    return re.sub(r"(ing|ed|es|s|ly|ion|ation)$", "", w)


def ideas(query: str, tags: list[str], moves: list[str], k: int = 4) -> list[tuple[str, str]]:
    """The k moves whose term best matches the clip: tag hits count 2, word hits in effect/use/example count 1.
    A move's term is scored once; `hold` (the static term) is never an idea."""
    q = {stem(w) for w in words(query)}
    want = set(tags)
    scored = []
    seen: set[str] = set()
    for m in moves:
        slug = MOVE_TERM.get(m, "")
        if m == "hold" or not slug or slug in seen:
            continue
        seen.add(slug)
        t = terms().get(slug)
        if not t:
            continue
        text = {stem(w) for w in words(f"{t['effect']} {t['use_case']} {t['example_scene']} {t['description']}")}
        score = 2 * len(want & set(t["tags"].split())) + len(q & text)
        if score:
            scored.append((score, m, f"{t['effect'].rstrip('.')}; use: {t['use_case'].rstrip('.')}"))
    scored.sort(key=lambda x: -x[0])
    return [(m, why) for _, m, why in scored[:k]]
