"""The gold scenes David is tried on (tests/eval/david/scenes, copied from Adam's: the groups stay independent) and a
plan written by hand for the phone call (the ChatGPT breakdown of plan/2026-11-05 §11 written as a David plan).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from contracts import sceneplan
from contracts.david.scene import BlockS, PlaceS, SceneS
from contracts.david.wire import DavidWire
from contracts.shotplan import Item

GOLD = Path(__file__).resolve().parents[1] / "eval" / "david"
NAME = "phone_call"


def raw(name: str = NAME) -> dict[str, Any]:
    return dict(yaml.safe_load((GOLD / "scenes" / f"{name}.yaml").read_text(encoding="utf-8"))["scene"])


def scene(name: str = NAME, *, cast: list[str] | None = None, others: tuple[str, ...] = ("Kasun",)) -> SceneS:
    """The gold scene as David is given it: the free rules' reading of each action on its clock, the speaker
    "Father (on the phone)" present as a voice."""
    sc = raw(name)
    items = [Item(b["index"], b["kind"], b["text"], b.get("speaker", ""), None, b.get("delivery", ""),
                  b.get("line_id")) for b in sc["blocks"]]
    items = sceneplan._read_unread(items)
    plain = cast if cast is not None else [*sc["cast"], *(["Father"] if name == NAME else [])]
    return SceneS(blocks=[BlockS.of(i) for i in items], cast=plain, others=list(others),
                  place=PlaceS(name=sc["place"]["name"], objects=sc["place"]["objects"]), envelope_s=90)


def ir(setting: str = "A bench by the lake, late afternoon", *, lens: str = "handheld, 35mm, f/2.8",
       movement: str = "locked-off", subjects: list[dict[str, str]] | None = None,
       lighting: str = "Low golden sun from camera left, soft, warm", beats: list[dict[str, str]] | None = None
       ) -> dict[str, Any]:
    return {
        "setting": setting,
        "cinematography": {"camera": lens, "angle": "eye level", "framing": "medium", "movement": movement,
                           "white_balance": "warm 4500K", "color_tone": "naturalistic, warm",
                           "depth_of_field": "Shallow, soft lake behind", "lens_artifacts": "none"},
        "lighting": lighting,
        "subjects": subjects if subjects is not None else [
            {"id": "", "description": "Anudi in a pale green kurta", "action": "listens", "position": "left end"}],
        "beats": beats if beats is not None else [
            {"time": "0-2s", "camera": "medium", "director_line": "She listens.", "action": "She sits still.",
             "performance": "She keeps smiling a moment too long."}],
        "audio": "Lake water, distant birds",
        "first_frame": {"composition": "Anudi left, lake behind", "subjects": ["Anudi"], "setting": "bench",
                        "lighting": "golden"},
    }


def shot(n: int, blocks: list[int], size: str, take: int, why: str, *, lines: list[str] | None = None, over: str = "",
         link: str = "cut", silence: bool = False, **kw: Any) -> dict[str, Any]:
    return {"n": n, "blocks": blocks, "lines": lines or [], "over": over, "take_s": take, "size": size, "link": link,
            "why": why, "ir": ir(**kw), "sound": {"ambience": "lake water", "effects": "", "music": "",
                                                  "silence": silence}}


def phone_call() -> DavidWire:
    """The phone call, planned the way a good director would: baseline, the buzz, the call over Anudi's face while
    the father is only heard, her smile fading, the phone put down, the goodbye, the walk out and Dasun watching."""
    return DavidWire.model_validate({
        "notes": "A mood breaks: a call decides Anudi's marriage and she answers with a smile that fades. It is her "
                 "scene; Dasun is the one who watches.",
        "shots": [
            shot(1, [0], "WIDE", 4, "Establish the bench and the ease between them."),
            shot(2, [1], "MS", 4, "Dasun's joke lands.", lines=["L1"]),
            shot(3, [2], "INSERT", 4, "The phone buzzes: the mood is about to break.", subjects=[]),
            shot(4, [3], "MCU", 4, "She answers, still smiling."),
            shot(5, [4], "CU", 6, "We hear the father; we watch her face take it in.", lines=["L4"], over="Anudi"),
            shot(6, [5, 6], "MCU", 4, "The smile goes; she agrees quietly.", lines=["L6"]),
            shot(7, [7], "INSERT", 4, "The phone goes face-down: a door closing.", subjects=[]),
            shot(8, [8], "MS", 4, "She leaves with a restrained goodbye.", lines=["L8"]),
            shot(9, [9], "WIDE", 6, "She walks away; the bench is suddenly too big."),
            shot(10, [], "MCU", 4, "Dasun watches her go and does not call after her.", subjects=[
                {"id": "", "description": "Dasun in a white shirt", "action": "watches the path",
                 "position": "right end of the bench"}]),
        ],
        "added": [{"shot": 10, "kind": "reaction", "what": "Dasun watches her go", "who": ["Dasun"], "object": ""}],
        "staging": {"zones": ["left end of the bench", "right end of the bench", "path"], "marks": [
            {"block": 0, "who": "Anudi", "zone": "left end of the bench", "facing": "right", "frame_side": "left",
             "holding": ""},
            {"block": 0, "who": "Dasun", "zone": "right end of the bench", "facing": "left", "frame_side": "right",
             "holding": ""},
            {"block": 3, "who": "Anudi", "zone": "left end of the bench", "facing": "right", "frame_side": "left",
             "holding": "her phone"},
            {"block": 7, "who": "Anudi", "zone": "left end of the bench", "facing": "right", "frame_side": "left",
             "holding": ""},
            {"block": 9, "who": "Anudi", "zone": "off", "facing": "away", "frame_side": "", "holding": "her bag"},
        ]},
        "end_state": {
            "people": [
                {"who": "Anudi", "where": "on the path away from the bench", "facing": "away", "holding": "her bag",
                 "look": "pale green kurta"},
                {"who": "Dasun", "where": "right end of the bench", "facing": "the path", "holding": "",
                 "look": "white shirt"},
                {"who": "Father", "where": "elsewhere, on the phone", "facing": "", "holding": "", "look": ""}],
            "props": [{"what": "her phone", "where": "in her bag"}], "time": "late afternoon",
            "light": "low golden sun"},
    })
