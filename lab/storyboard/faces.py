"""Paint a FACE SHEET for one person: the same face at several angles and a neutral / serious expression, made from
the portrait on their look sheet (plan/2026-11-13e §6f).

Why: every look/character sheet holds ONE face, front-on, smiling, in studio light (the other views are headless). A
shot asks for that person serious, turned, at night, so the image model invents the missing face and it drifts. A
face sheet gives it the angles and expressions to copy.

The portrait is cut from the look sheet by code (the right-hand fifth) and sent large. One paid image call, checked by
the lab's ledger guard. The result is saved as `input/<name>/refs/face_<person>.png`.

    .venv/Scripts/python.exe lab/storyboard/faces.py --input scene2 --person Dinu
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run as lab  # noqa: E402  (also puts src/libs on the path)

from contracts.safe_depiction import blocking  # noqa: E402

QUALITY = "high"  # a face sheet is reused by every board and frame: worth the detail

PROMPT = (
    "A face reference sheet for a Sri Lankan television drama: the SAME person as image 1, photographed six times in "
    "one image, laid out 3 across and 2 down, each a head-and-shoulders photograph on the same plain mid-grey studio "
    "backdrop, separated by thin white gutters. Top row: (1) facing the camera, neutral relaxed expression, mouth "
    "closed; (2) three-quarter view, head turned toward the left of the picture, neutral; (3) three-quarter view, "
    "head turned toward the right of the picture, neutral. Bottom row: (4) full profile facing the left of the "
    "picture; (5) full profile facing the right of the picture; (6) facing the camera, serious and worried, brows "
    "slightly drawn, mouth closed. "
    "Exactly the person in image 1 in every photograph: the same face shape, age, skin tone, eyes, nose, lips, ears, "
    "hairline, hair and facial hair. Do not age them, do not make them heavier or more weathered. Only the head angle "
    "and the expression change. The same top as in image 1. Soft, even studio light from the front in every "
    "photograph. Photorealistic. No text, no numbers, no labels."
)


def portrait(look_sheet: Path) -> bytes:
    """The right-hand fifth of a look sheet: its one face."""
    from PIL import Image
    im = Image.open(look_sheet).convert("RGB")
    w, h = im.size
    crop = im.crop((round(w * 0.735), 0, w, h))
    buf = io.BytesIO()
    crop.save(buf, format="PNG")
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--person", required=True)
    ap.add_argument("--hypothesis", default="")
    ap.add_argument("--quality", choices=["low", "medium", "high"], default=QUALITY)
    a = ap.parse_args()

    bundle = json.loads((HERE / "input" / a.input / "bundle.json").read_text(encoding="utf-8"))
    look = next(r for r in bundle["references"] if r["role"] == "look" and r["name"] == a.person)
    face_in = portrait(HERE / look["file"])
    if blocking(PROMPT):
        print("STOP: blocked words in the face prompt")
        return 1
    worst = lab.dollars(lab.IMAGE_MODEL, lab.IMAGE_IN_BASE + lab.IMAGE_IN_PER_REF, 0, lab.IMAGE_WORST_OUT[a.quality])
    lab.guard(worst, "face sheet")
    out = lab.next_run()
    (out / "portrait_in.png").write_bytes(face_in)
    (out / "face_prompt.txt").write_text(PROMPT, encoding="utf-8")
    print("run:", out.name, "face sheet for", a.person, f"(worst ${worst:.3f})")
    t0 = time.time()
    img = lab.client().images.edit(model=lab.IMAGE_MODEL, image=[("portrait.png", face_in, "image/png")],
                                   prompt=PROMPT, size=lab.IMAGE_SIZE, quality=a.quality)
    iu = getattr(img, "usage", None)
    usage = {"input": int(getattr(iu, "input_tokens", 0) or 0), "output": int(getattr(iu, "output_tokens", 0) or 0)}
    cost = lab.book(out.name, f"face-{a.person}", lab.IMAGE_MODEL, usage, "done", a.hypothesis)
    png = base64.b64decode(img.data[0].b64_json)
    (out / f"face_{a.person}.png").write_bytes(png)
    target = HERE / "input" / a.input / "refs" / f"face_{a.person}.png"
    target.write_bytes(png)
    print(f"{time.time() - t0:.0f}s, {usage}, ${cost:.4f} -> {target.relative_to(HERE)}; ledger ${lab.spent():.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
