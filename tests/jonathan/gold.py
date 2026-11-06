"""The gold scenes Jonathan is tried on (tests/eval/jonathan/scenes, copied from Adam's: the groups stay independent)
and a plan written by hand for the phone call, in the cinematic lab's shape: a treatment, three sequences and fifteen
shots with their size, angle, lens and kept seconds. It passes every hard check and meets every craft measure, so a
scripted author that answers it is a scene the stabiliser leaves alone.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from contracts import sceneplan
from contracts.jonathan.measures import Craft
from contracts.jonathan.scene import BlockS, PlaceS, SceneS
from contracts.jonathan.wire import JonathanWire
from contracts.shotplan import Item

GOLD = Path(__file__).resolve().parents[1] / "eval" / "jonathan"
NAME = "phone_call"
# what the world's canon gives the craft measures for the phone call (tests/jonathan/world.py)
CRAFT = Craft(codes={"Anudi": "C01", "Dasun": "C02", "Father": "C03"}, story_objects=["bench", "phone", "bag"],
              guide_s=90)


def raw(name: str = NAME) -> dict[str, Any]:
    return dict(yaml.safe_load((GOLD / "scenes" / f"{name}.yaml").read_text(encoding="utf-8"))["scene"])


def scene(name: str = NAME, *, cast: list[str] | None = None, others: tuple[str, ...] = ("Kasun",)) -> SceneS:
    """The gold scene as Jonathan is given it: the free rules' reading of each action on its clock, the speaker
    "Father (on the phone)" present as a voice."""
    sc = raw(name)
    items = [Item(b["index"], b["kind"], b["text"], b.get("speaker", ""), None, b.get("delivery", ""),
                  b.get("line_id")) for b in sc["blocks"]]
    items = sceneplan._read_unread(items)
    plain = cast if cast is not None else [*sc["cast"], *(["Father"] if name == NAME else [])]
    return SceneS(blocks=[BlockS.of(i) for i in items], cast=plain, others=list(others),
                  place=PlaceS(name=sc["place"]["name"], objects=sc["place"]["objects"]), envelope_s=90)


ANUDI = {"id": "C01", "description": "Anudi in a pale green kurta", "action": "listens", "position": "left end"}
DASUN = {"id": "C02", "description": "Dasun in a white shirt", "action": "watches her", "position": "right end"}


def ir(setting: str = "A bench by the lake, late afternoon", *, lens: str = "handheld, 35mm, f/2.8",
       movement: str = "locked-off", subjects: list[dict[str, str]] | None = None,
       lighting: str = "Low golden sun from camera left, soft, warm", beats: list[dict[str, str]] | None = None,
       action: str = "She sits still.") -> dict[str, Any]:
    return {
        "setting": setting,
        "cinematography": {"camera": lens, "angle": "eye level", "framing": "medium", "movement": movement,
                           "white_balance": "warm 4500K", "color_tone": "naturalistic, warm",
                           "depth_of_field": "Shallow, soft lake behind", "lens_artifacts": "none"},
        "lighting": lighting,
        "subjects": subjects if subjects is not None else [ANUDI],
        "beats": beats if beats is not None else [
            {"time": "0-2s", "camera": "medium", "director_line": "She listens.", "action": action,
             "performance": "She keeps smiling a moment too long."}],
        "audio": "Lake water, distant birds",
        "first_frame": {"composition": "Anudi left, lake behind", "subjects": ["Anudi"], "setting": "bench",
                        "lighting": "golden"},
    }


def shot(n: int, sequence: str, blocks: list[int], size: str, take: int, use: int, why: str, *,
         lines: list[str] | None = None, over: str = "", link: str = "cut", silence: bool = False,
         angle: str = "eye level", lens: str = "50mm: the scene's eye", **kw: Any) -> dict[str, Any]:
    return {"n": n, "sequence": sequence, "blocks": blocks, "lines": lines or [], "over": over, "size": size,
            "angle": angle, "lens": lens, "take_s": take, "use_s": use, "link": link, "why": why, "ir": ir(**kw),
            "sound": {"ambience": "lake water", "effects": "", "music": "", "silence": silence}}


def treatment() -> dict[str, Any]:
    return {
        "logline": "A call from her father decides Anudi's marriage and ends an easy afternoon on a lakeside bench.",
        "arc": [{"beat": "Ease", "blocks": {"first": 0, "last": 1}, "feeling": "warmth, a private joke"},
                {"beat": "The call", "blocks": {"first": 2, "last": 6}, "feeling": "the floor drops away"},
                {"beat": "The goodbye", "blocks": {"first": 7, "last": 9}, "feeling": "a door quietly closing"}],
        "approach": "Wide and still for the ease, closer and longer lenses as the call lands, a held wide for the "
                    "exit.",
        "colour_script": [
            {"sequence": "A", "palette": "gold, green", "light": "low late-afternoon sun from the left",
             "grade": "warm and open"},
            {"sequence": "B", "palette": "gold turning grey-green", "light": "the same low sun",
             "grade": "warmth drained from the mids"},
            {"sequence": "C", "palette": "cool green, long shadows", "light": "the same low sun",
             "grade": "cool, lower contrast"}],
        "geography": "Anudi frame left on the bench, Dasun frame right, the lake behind; the camera stays on the path "
                     "side of the bench.",
        "key_image": "The phone face-down on the bench in the gap between them.",
        "advice": ["The call's words are heard over her face; the phone's screen is never read."]}


def phone_call() -> JonathanWire:
    """The phone call, planned the way a good team would: the world, Dasun's joke and Anudi's laugh, the buzz, the call
    heard over her face while the father is only a voice, the phone put down in two shots, the goodbye, the bag, the
    walk out held wide."""
    phone = [{"time": "0-4s", "camera": "insert", "director_line": "The phone on the bench.",
              "action": "The phone buzzes and lights on the bench.", "performance": "A hand rests near it."}]
    return JonathanWire.model_validate({
        "treatment": treatment(),
        "sequences": [{"id": "A", "title": "Ease", "purpose": "the world and the joke",
                       "shots": {"first": 1, "last": 3}},
                      {"id": "B", "title": "The call", "purpose": "the mood breaks", "shots": {"first": 4, "last": 11}},
                      {"id": "C", "title": "The goodbye", "purpose": "she leaves", "shots": {"first": 12, "last": 15}}],
        "shots": [
            shot(1, "A", [0], "EWS", 4, 3, "The world: the bench small against the lake, the two of them at ease.",
                 lens="24mm: the place", subjects=[ANUDI, DASUN]),
            shot(2, "A", [1], "MS", 4, 4, "The joke: Dasun's line lands.", lines=["L1"], subjects=[DASUN]),
            shot(3, "A", [], "MCU", 4, 2, "The release: Anudi laughs.", lens="85mm: her face",
                 action="She laughs, head back."),
            shot(4, "B", [2], "INSERT", 4, 3, "The trigger: the phone buzzes on the bench.", subjects=[], beats=phone),
            shot(5, "B", [3], "MCU", 4, 3, "Still smiling, she looks down at it.", action="She glances down."),
            shot(6, "B", [3], "INSERT", 4, 2, "The choice: her hand lifts the phone; the camera tilts up with it.",
                 subjects=[], movement="tilt up with the hand", action="Her hand lifts the phone from the bench."),
            shot(7, "B", [4], "CU", 6, 6, "The blow: we hear the father and watch her face take it in.",
                 lines=["L4"], over="Anudi", lens="85mm: no escape"),
            shot(8, "B", [5, 6], "MCU", 4, 4, "The turn: the smile goes; she agrees quietly.", lines=["L6"]),
            shot(9, "B", [], "MS", 4, 2, "The witness: Dasun understands.", subjects=[DASUN],
                 action="He looks at her and stays still."),
            shot(10, "B", [7], "INSERT", 4, 3, "The end of the call: her thumb ends it.", subjects=[],
                 action="Her thumb ends the call on the phone."),
            shot(11, "B", [7], "ECU", 4, 2, "A door closing: the phone face-down on the bench.", subjects=[],
                 action="The phone lies face-down on the bench."),
            shot(12, "C", [8], "MS", 4, 4, "The goodbye, restrained.", lines=["L8"]),
            shot(13, "C", [], "MCU", 4, 2, "Dasun takes the goodbye and does not argue.", subjects=[DASUN],
                 action="He nods once."),
            shot(14, "C", [9], "INSERT", 6, 2, "Her hand takes the bag; the camera pans with it.", subjects=[],
                 movement="pan with the bag", action="Her hand takes the bag from the bench."),
            shot(15, "C", [9], "WIDE", 6, 4, "The exit: she walks out; the bench is suddenly too big.",
                 lens="24mm: the empty place", movement="slow pan following her", subjects=[ANUDI, DASUN],
                 action="She walks away along the path."),
        ],
        "added": [{"shot": 3, "kind": "reaction", "what": "Anudi laughs at the joke", "who": ["Anudi"], "object": ""},
                  {"shot": 9, "kind": "reaction", "what": "Dasun understands", "who": ["Dasun"], "object": ""},
                  {"shot": 13, "kind": "reaction", "what": "Dasun takes the goodbye", "who": ["Dasun"], "object": ""}],
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
