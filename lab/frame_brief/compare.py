"""Phase 0 of plan/2026-11-11b: the first-frame prompt before and after, side by side, for every clip of a Raphael run.
No model, no network, $0.

    python lab/frame_brief/compare.py [run dir] [name]
    (default: lab/two_memories/runs/pipeline_ekama_run3/12_raphael → lab/frame_brief/runs/ekama_run3.md)

Both prompts are built from the same clip, the same people (names only, as on the shot that started this plan: "People:
Dinu."), the same pictures (a character sheet per person seen, the place's plate) and the product's own camera
recommendation. Only the prompt code differs: `old_prompt` is `contracts.producer.frame_prompt` as it stood at
a8feb50, copied word for word.

The check FAILS (exit 1) when a fact the planner wrote does not reach the new prompt: the IR's white balance, colour
tone and fuller light, the time of day of the heading, the weather its words name, each seen person's position; and the
hand-listed facts of `expect_ekama.json` (night, rain, 4300K, the red thread on the left wrist).
"""
from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "src" / "libs")]

from contracts.frame_brief import frame_brief, time_phrase, weather_phrase  # noqa: E402
from contracts.producer import (  # noqa: E402
    CAMERA_OPTIONS,
    FRAMING_LABEL,
    CameraField,
    CameraSettings,
    CastMember,
    camera_sentence,
    default_camera,
    identity_line,
)
from contracts.raphael.wire import FRAMING  # noqa: E402
from hiru_ai.steps.raphael.raphael_write.logic import camera_hint  # noqa: E402

RUN = ROOT / "lab" / "two_memories" / "runs" / "pipeline_ekama_run3" / "12_raphael"
PACKETS = ROOT / "lab" / "two_memories" / "runs" / "packets_ekama.json"
EXPECT = Path(__file__).with_name("expect_ekama.json")
Row = dict[str, Any]


# ── the old prompt, as it stood (a8feb50 contracts/producer.py) ─────────────────────────────


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split())


def old_prompt(*, ir: Mapping[str, Any], camera: CameraSettings, aspect_ratio: str, cast: list[CastMember],
               references: list[str] | None = None, recommended_framing: str = "", unseen: str = "",
               hands: str = "") -> str:
    frame = ir.get("first_frame") if isinstance(ir.get("first_frame"), Mapping) else {}
    subjects = frame.get("subjects") if isinstance(frame, Mapping) else None
    subject_text = "; ".join(_clean(s) for s in subjects) if isinstance(subjects, list) else _clean(subjects)
    parts = ["Photorealistic still frame from a Sri Lankan television drama, shot on a cinema camera with "
             "real optics and natural imperfections."]
    if references:
        named = "; ".join(f"image {n} is {label}" for n, label in enumerate(references, start=1))
        parts.append(f"Reference images, in order: {named}. Match them exactly: the same faces, hair, skin "
                     "tone and build, the same place. Do not redesign anyone.")
        if any(label.startswith("the character sheet") for label in references):
            parts.append("A character sheet shows a plain reference outfit: take clothes from the People "
                         "line, never from the sheet, and if it names none dress them in plain everyday "
                         "clothes.")
    parts.append(f"Camera: {camera_sentence(camera)}")
    if recommended_framing and camera.framing != recommended_framing:
        parts.append(f"Compose it as a {camera.framing.lower()}.")
    for text in (_clean(frame.get("composition")) if isinstance(frame, Mapping) else "", subject_text):
        if text:
            parts.append(text if text.endswith(".") else f"{text}.")
    people = [identity_line(c) for c in cast if c.kind == "character"]
    if people:
        parts.append("People: " + " | ".join(people) + ".")
    if hands:
        parts.append(hands)
    setting = (_clean(frame.get("setting")) if isinstance(frame, Mapping) else "") or _clean(ir.get("setting"))
    if setting:
        parts.append(f"Setting: {setting.rstrip('.')}.")
    light = (_clean(frame.get("lighting")) if isinstance(frame, Mapping) else "") or _clean(ir.get("lighting"))
    parts.append(f"Lighting: {(light or camera.lighting).rstrip('.')}.")
    if unseen:
        parts.append(unseen)
    parts.append("The people, place and everyday details are Sri Lankan.")
    parts.append("9:16 vertical framing." if aspect_ratio == "9:16" else f"{aspect_ratio} framing.")
    parts.append("A single still frame: no text, no watermark, no captions, no collage, no split panels.")
    return " ".join(parts)


def old_hint(ir: Mapping[str, Any]) -> Row:
    """`camera_hint` as it stood: a lens or stop only on an exact match."""
    hint = dict(camera_hint(ir))
    rig = _clean((ir.get("cinematography") or {}).get("camera"))
    for key, f in (("lens", CameraField.LENS), ("aperture", CameraField.APERTURE)):
        exact = next((x for x in CAMERA_OPTIONS[f] if x in rig), "")
        if exact:
            hint[key] = exact
        else:
            hint.pop(key, None)
    return hint


# ── the comparison ──────────────────────────────────────────────────────────────────────────


def facts_of(clip: Row, heading: str, seen: list[str]) -> list[str]:
    """What the planner wrote that must reach the new prompt, in the words the prompt uses."""
    ir = clip["ir"]
    cine = ir.get("cinematography") or {}
    out = [_clean(cine.get("white_balance")), _clean(cine.get("color_tone")), _clean(ir.get("lighting")).rstrip(".")]
    when = time_phrase({"heading": heading})
    if when:
        out.append(f"Time: {when}")
    frame = ir.get("first_frame") or {}
    weather = weather_phrase(_clean(ir.get("setting")), _clean(frame.get("setting")), _clean(ir.get("lighting")),
                             _clean(frame.get("lighting")), _clean(ir.get("audio")))
    if weather:
        out.append(f"Weather: {weather}")
    for s in ir.get("subjects") or []:
        name = _clean(s.get("description")).split(",")[0]
        if name in seen and _clean(s.get("position")):
            out.append(_clean(s.get("position")).rstrip("."))
    return [f for f in out if f]


def compare(run: Path, packets: Mapping[str, Any], expect: Mapping[str, list[str]]) -> tuple[str, int]:
    lines = ["# First-frame prompt: before and after (plan/2026-11-11b, Phase 0)", "",
             f"Run: `{run.relative_to(ROOT).as_posix()}`. No model, $0. Built by `lab/frame_brief/compare.py`.", "",
             "| Slate | Old chars | New chars | Cut to fit | Facts in old | Facts in new | Missing from new |",
             "|---|---|---|---|---|---|---|"]
    body: list[str] = []
    failures = 0
    for path in sorted(run.glob("*.json")):
        scene_id = path.stem
        result = json.loads(path.read_text(encoding="utf-8"))["result"]
        packet = packets.get(scene_id) or {}
        heading = str((packet.get("A_scene") or {}).get("heading") or "")
        people = {str(p["id"]): str(p["name"]) for p in packet.get("B_people") or []}
        place = str((packet.get("C_place") or {}).get("name") or "")
        scene = {"heading": heading, "raphael": result}
        for clip in result["clips"]:
            ir = clip.get("ir")
            if not ir:
                continue
            seen = [people[str(s.get("id"))] for s in ir.get("subjects") or [] if str(s.get("id")) in people]
            cast = [CastMember(id=n, code=c, name=n) for c, n in people.items() if n in seen]
            labels = [f"the character sheet for {n}" for n in seen] + ([f"the location plate for {place}"]
                                                                       if place else [])
            framing = FRAMING.get(clip["size"], clip["size"])  # as raphael_write does
            base = default_camera(framing, heading=heading)
            old_cam = base.with_overrides(old_hint(ir))
            new_cam = base.with_overrides(camera_hint(ir))
            old = old_prompt(ir=ir, camera=old_cam, aspect_ratio="16:9", cast=cast, references=labels,
                             recommended_framing=FRAMING_LABEL.get(framing, ""))
            brief = frame_brief(ir=ir, camera=new_cam, aspect_ratio="16:9", cast=cast, references=labels,
                                recommended=new_cam, scene=scene, shot={"slate": clip["slate"]})
            new = brief.text()
            facts = facts_of(clip, heading, seen) + list(expect.get(f"{scene_id}/{clip['slate']}") or [])
            missing = [f for f in facts if f.lower() not in new.lower()]
            in_old = sum(f.lower() in old.lower() for f in facts)
            failures += bool(missing)
            lines.append(f"| {scene_id} {clip['slate']} | {len(old)} | {len(new)} | {', '.join(brief.cut) or '-'} | "
                         f"{in_old}/{len(facts)} | {len(facts) - len(missing)}/{len(facts)} | "
                         f"{'; '.join(missing) or '-'} |")
            body += [f"## {scene_id} {clip['slate']} ({clip['size']}, {clip.get('role', '')})", "",
                     f"_{_clean(clip.get('summary'))}_", "", "### Old", "", "```", old, "```", "", "### New, by section",
                     ""]
            for s in brief.view():
                body.append(f"- **{s['title']}** ({', '.join(s['sources'])}): {s['text']}")
            body.append("")
    lines += ["", f"{failures} clip(s) missing a fact." if failures else "Every fact reached the new prompt.", ""]
    return "\n".join(lines + body), failures


def main(argv: list[str]) -> int:
    run = Path(argv[0]) if argv else RUN
    name = argv[1] if len(argv) > 1 else "ekama_run3"
    packets = json.loads(PACKETS.read_text(encoding="utf-8")) if PACKETS.exists() else {}
    expect = json.loads(EXPECT.read_text(encoding="utf-8")) if EXPECT.exists() else {}
    text, failures = compare(run, packets, expect)
    out = Path(__file__).with_name("runs") / f"{name}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"{out.relative_to(ROOT).as_posix()}: {failures} clip(s) missing a fact")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
