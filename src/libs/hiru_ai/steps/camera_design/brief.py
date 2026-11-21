"""What the Camera agent is told (plan/2026-11-20c §4), ported from `lab/camera_agent/run.py` (`clips_brief`,
`scene_brief`):

    scene_part(scene_text)        the <scene> part, the <moves> menu and the <omni> table: identical for every call of a
                                  scene (it caches, D3)
    clips_part(clips, ideas)      the <clips> part: every clip in cut order, the planner's SIZE fixed
    current_part(clips)           one-shot mode: the scene's camera as it stands, one line per clip

`clips` are the dicts `facts.clip_facts` builds; `ideas` is slate -> [(move, why)] from `kb.ideas`.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from contracts import camera as cam
from hiru_ai.steps.camera_design import kb

Row = dict[str, Any]
NL = "\n"


def scene_part(scene_text: str) -> str:
    return f"{scene_text.strip()}\n\n{kb.menu()}\n\n{cam.omni_brief()}"


def clip_block(clip: Mapping[str, Any], n: int, offered: Sequence[tuple[str, str]] = ()) -> str:
    out = [f"<clip slate=\"{clip['slate']}\" n=\"{n}\">"]
    out.append(f"Setup {clip.get('setup') or '-'}; role {clip.get('role') or 'shot'}; SIZE {clip.get('size')} "
               f"({clip.get('framing_words') or ''}); take {clip.get('take_s')} s, handles "
               f"{clip.get('handle_in_s', 0)} s in / {clip.get('handle_out_s', 0)} s out; sound "
               f"{clip.get('sound_mode') or '-'}.")
    out.append(f"Planner's camera words (a hint): technique {clip.get('technique') or '-'}; "
               f"{clip.get('cine_camera') or ''}; angle {clip.get('angle') or '-'}; lens {clip.get('lens') or '-'}; "
               f"movement: {clip.get('movement') or ''}; depth: {clip.get('depth') or ''}.")
    if clip.get("cinematic"):
        out.append("A cinematic clip: the planner made it for its technique.")
    if clip.get("why"):
        out.append(f"Why the planner made it: {clip['why']}")
    if clip.get("summary"):
        out.append(f"What happens: {clip['summary']}")
    for s in clip.get("in_frame") or []:
        out.append(f"In frame: {s.get('description', '')} Where: {s.get('position', '')} Does: {s.get('action', '')}")
    for name in clip.get("heard") or []:
        out.append(f"Only heard, never seen: {name}")
    if not clip.get("in_frame"):
        out.append("No person in frame.")
    if clip.get("opening"):
        out.append(f"Opening picture: {clip['opening']}")
    beats = clip.get("beats") or []
    if beats:
        out.append("Beats: " + " | ".join(f"{b.get('time', '')}: {b.get('action', '')}" for b in beats))
    spoken = clip.get("spoken") or []
    if spoken:
        out.append("Spoken here: " + "; ".join(
            f"{s['lid']} {s['speaker']}{' (heard, not seen)' if s.get('heard') else ''} (~{s['seconds']} s)"
            for s in spoken))
    else:
        out.append("Nobody speaks on camera in this clip.")
    if offered:
        out.append("Ideas from the knowledge base (ideas, not orders): " + " | ".join(f"{m}: {w}" for m, w in offered))
    out.append("</clip>")
    return NL.join(out)


def clips_part(clips: Sequence[Mapping[str, Any]], ideas: Mapping[str, Sequence[tuple[str, str]]] | None = None) -> str:
    ideas = ideas or {}
    out = ["<clips>", "In cut order. SIZE is fixed (the clip opens on it)."]
    out += [clip_block(c, n, ideas.get(str(c["slate"]), ())) for n, c in enumerate(clips, start=1)]
    out.append("</clips>")
    return NL.join(out)


def current_part(clips: Sequence[Mapping[str, Any]]) -> str:
    """One line per clip of the scene's camera as it stands (one-shot mode): its slate, move, speed and sentence."""
    out = []
    for c in clips:
        now = c.get("current") or {}
        if now:
            felt = (f"{now['moment']} {now.get('intensity', '')}, power {now.get('power', '')}; "
                    if now.get("moment") else "")
            out.append(f"{c['slate']}: {felt}{now.get('move', '')} / {now.get('speed', '')}, {now.get('angle', '')}, "
                       f"{now.get('lens', '')} — {now.get('camera_sentence', '')}")
        else:
            out.append(f"{c['slate']}: not designed yet")
    return NL.join(out)
