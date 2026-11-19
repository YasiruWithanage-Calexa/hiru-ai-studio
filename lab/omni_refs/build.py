"""The lab's Omni request: the first frame AND the people's sheets in one request, cited in plain words by order.

Google's Omni page (read 2026-11-18): the `<FIRST_FRAME>` / `<IMAGE_REF_0>` control strings are "deprecated and unsupported
in future models. Describe how each image or video should be used in natural language instead." Up to 6 reference images on
gemini-omni-1.2-flash, at most 3 per character for up to 2 characters. `task` is a fallback that "adds strict constraints,
such as limiting input images", so variant B leaves it out and lets the model read each image's job from the words.

Variants (one shot, one seed policy, 360p, so only the request differs):
  A  today's product request: the first frame only, `<FIRST_FRAME>` block, task image_to_video (`build_omni_input`).
  B  frame + face and look sheets, "Image 1 is ..." sentences in the attached order, NO task.
  C  the same as B with task reference_to_video (does forcing the task lose the literal opening frame?).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MODEL = "gemini-omni-1.2-flash"
RESOLUTION = "360p"  # the lowest Omni takes: a look test, not a deliverable
MAX_IMAGES = 6  # gemini-omni-1.2-flash, Google's Omni page
MAX_PER_PERSON = 3


@dataclass(frozen=True)
class Image:
    file: str  # under the input folder
    sentence: str  # what the model is told this picture is for
    person: str | None = None  # the person it shows, for the per-person cap


def images_for(meta: dict[str, Any]) -> list[Image]:
    """Image 1 is the first frame; then, for each person in the shot's order, their face sheet then their look sheet."""
    out = [Image("frame.png",
                 "is the opening frame of this shot. The video starts exactly on this picture: the same framing, "
                 "people, place, weather and light, and everything that happens grows out of it.")]
    for p in meta["people"]:
        name = p["name"] if p["name"][:1].isupper() else f"the {p['name']}"
        cap = name[:1].upper() + name[1:]  # at the start of a sentence
        out.append(Image(f"face_{p['code']}.png",
                         f"is the face sheet for {name}: several angles of the same face. {cap}'s face, age, "
                         f"skin tone and hair come only from this sheet, at every angle and expression, including when "
                         f"{name} turns or moves closer to the camera.", p["code"]))
        wear = "; ".join(x.strip().rstrip(".") for x in (p.get("outfit"), p.get("accessories"))
                         if x and x.strip().rstrip(".").lower() not in ("", "none"))
        out.append(Image(f"look_{p['code']}.png",
                         f"is the look sheet for {name}: exactly what {name} wears in this shot, head to toe"
                         + (f" ({wear})" if wear else "") + f". When more of {name} comes into view, the clothes, "
                         f"shoes and things carried match this sheet exactly.", p["code"]))
    return out


def check(images: list[Image]) -> list[str]:
    """Why this list may not be sent, or nothing."""
    out = []
    if len(images) > MAX_IMAGES:
        out.append(f"{len(images)} images; gemini-omni-1.2-flash takes at most {MAX_IMAGES}.")
    for person in {i.person for i in images if i.person}:
        n = sum(1 for i in images if i.person == person)
        if n > MAX_PER_PERSON:
            out.append(f"{n} images of {person}; at most {MAX_PER_PERSON} per person.")
    if len({i.person for i in images if i.person}) > 2:
        out.append("more than 2 people have sheets; Omni 1.2 takes sheets for up to 2.")
    return out


def citation_block(images: list[Image]) -> str:
    lines = [f"Image {n} {img.sentence}" for n, img in enumerate(images, start=1)]
    tail = (f"Images 2 to {len(images)} are references only: never show a sheet, its grey backdrop or its panels in the "
            "video, and never cut to them. Where the words above describe someone's clothes or face differently from "
            "these pictures, the pictures win.") if len(images) > 1 else ""
    return "Reference images, in the order attached:\n" + "\n".join(lines) + ("\n" + tail if tail else "")


def request_b(meta: dict[str, Any], *, task: str | None) -> dict[str, Any]:
    """Variant B (task None) or C (task "reference_to_video"): the body without image bytes."""
    images = images_for(meta)
    problems = check(images)
    if problems:
        raise ValueError("; ".join(problems))
    prompt = meta["prose"].strip() + "\n\n" + citation_block(images)
    return {"model": MODEL, "prompt": prompt, "images": [i.file for i in images], "task": task,
            "aspect_ratio": meta["aspect_ratio"], "duration_s": int(meta["duration_s"])}


def request_a(meta: dict[str, Any]) -> dict[str, Any]:
    """Variant A: exactly what the product builds today for this shot (frame only), through its own adapter."""
    from uuid import UUID

    from contracts.video_gen import RefBinding, RefSource, RenderSpec, build_omni_input

    frame = RefBinding(slot="first_frame", label="the opening frame", origin="code",
                       source=RefSource(kind="accepted_frame", id=UUID(meta["frame_id"]), path="frame.png",
                                        bucket="frames"))
    spec = RenderSpec(engine="omni_flash", model=MODEL, prose=meta["prose"], references=[frame], resolution=RESOLUTION,
                      aspect_ratio=meta["aspect_ratio"], duration_s=int(meta["duration_s"]))
    built = build_omni_input(spec)
    return {"model": MODEL, "prompt": built["prompt"], "images": ["frame.png"], "task": "image_to_video",
            "aspect_ratio": meta["aspect_ratio"], "duration_s": int(meta["duration_s"])}


def body(req: dict[str, Any], folder: Path, *, with_bytes: bool) -> dict[str, Any]:
    """The Interactions API body (`video_render.engine.omni.submit`'s shape), images first in order, then the text."""
    import base64

    parts: list[dict[str, Any]] = []
    for name in req["images"]:
        data = (folder / name).read_bytes() if with_bytes else b""
        parts.append({"type": "image", "mime_type": "image/png",
                      "data": base64.b64encode(data).decode("ascii") if with_bytes else f"<{name}>"})
    parts.append({"type": "text", "text": req["prompt"]})
    out: dict[str, Any] = {
        "model": req["model"], "input": parts, "background": False, "store": True,
        "response_format": {"type": "video", "aspect_ratio": req["aspect_ratio"], "resolution": RESOLUTION,
                            "duration": f"{req['duration_s']}s", "delivery": "uri"},
    }
    if req["task"]:
        out["generation_config"] = {"video_config": {"task": req["task"]}}
    return out


def load(folder: Path) -> dict[str, Any]:
    return json.loads((folder / "shot.json").read_text(encoding="utf-8"))
