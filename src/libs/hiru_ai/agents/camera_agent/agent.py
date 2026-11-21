"""camera_agent hooks (plan/2026-11-20c §3): ONE agent designs everything the camera does, for a whole scene at once.

The lab (`lab/camera_agent`, gpt-6.1-sol at medium effort) proved it on Api Denna E01: given the scene, every clip in
cut order (the planner's size fixed), the knowledge base's moves and what the video model performs, it designs moves
across the cuts with a reason for each, and one camera sentence per clip.

The message: the scene part first, as its OWN message (`shared_message`), byte for byte the same for every call of a
scene, so it caches; then the clips. A one-shot call (an Ask, a clip a chat turn changed) adds the scene's camera as it
stands and names the one clip to answer for. On a repair the first answer and the faults follow. No `fallback`: with no
model the agent is not called, and a failed call is the caller's to report (D10).
"""
from __future__ import annotations

from hiru_ai.agents.camera_agent.schema import Input


def shared_message(inp: Input) -> str:
    """The part every call of the scene shares, sent before the call's own message."""
    return inp.scene


def user_message(inp: Input) -> str:
    parts = [inp.clips]
    if inp.focus:
        which = ", ".join(inp.focus)
        one = len(inp.focus) == 1
        scene_camera = (f"<scene_camera>\nCamera language so far: {inp.language or '(none yet)'}\n{inp.current}\n"
                        "</scene_camera>")
        asked = (f"The person asks for clip {which} only: \"{inp.note}\"\n" if inp.note else
                 f"Clip{'' if one else 's'} {which} {'is' if one else 'are'} new or changed.\n")
        parts += [scene_camera if inp.current or inp.language else "",
                  asked + f"Design clip{'' if one else 's'} {which} only, in the scene's camera language, "
                          "matching the clips before and after. Answer `clips` with "
                  + ("that one clip" if one else f"those {len(inp.focus)} clips, in that order")
                  + "; keep `camera_language` as it is."]
    if inp.repair:
        parts += [f"<your_first_answer>\n{inp.previous}\n</your_first_answer>" if inp.previous else "",
                  "Code checked your answer and found:\n- " + "\n- ".join(inp.repair)
                  + "\nAnswer again, complete" + ("" if inp.focus else " (every clip)")
                  + ", with these fixed and everything else kept."]
    return "\n\n".join(p for p in parts if p)
