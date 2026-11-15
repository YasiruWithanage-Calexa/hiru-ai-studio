"""Test the second half of the idea: paint ONE shot's real first frame from its storyboard panel.

The panel is cut out by code (`runs/<run>/shots/shot_NN.png`) and sent as the product's "approved draft"
(`contracts.frame_brief.references_block` wording, unchanged). Variant `panel` sends the look/place/prop sheets + the
panel; variant `board` also sends the whole board (without the code-drawn tags, so no tag can be copied) and says which
cell this shot is. Each variant is one paid image call, checked by the same ledger guard as `run.py`.

    .venv/Scripts/python.exe lab/storyboard/frame.py --run run_004 --input scene2 --shot 7 --variants panel,board
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run as lab  # noqa: E402  (also puts src/libs on the path)

from contracts.frame_brief import CLOSE_PLACE, CLOSE_SINGLE, LEAD, references_block  # noqa: E402
from contracts.producer import DRAFT_LABEL  # noqa: E402
from contracts.safe_depiction import blocking  # noqa: E402

BOARD_LABEL = "the storyboard of this scene"
QUALITY = "high"  # a first frame is the finished picture (the person may ask for less with --quality)


def scene_world(world: str) -> str:
    """The board's World paragraph without its sentences about the board itself (panels, grid, gutters): a frame
    prompt that mentions sixteen panels invites a grid."""
    keep = [x for x in re.split(r"(?<=[.!?])\s+", world.strip())
            if not re.search(r"\b(panels?|storyboard|grid|gutters?)\b", x, re.IGNORECASE)]
    return " ".join(keep)


def unmannequin(text: str, colours: dict[str, str]) -> str:
    """The writer's mannequin words turned back into people: "the red mannequin" -> "Dinu", "red head" -> "head"."""
    for name, c in colours.items():
        text = re.sub(rf"\bthe {c} mannequin\b", name, text, flags=re.IGNORECASE)
        text = re.sub(rf"\b{c} mannequin\b", name, text, flags=re.IGNORECASE)
        text = re.sub(rf"\b(smooth,? )?{c} (?=(head|hands?|arms?|body|figure|shoulders?|chest|torso)\b)", "", text,
                      flags=re.IGNORECASE)
    return re.sub(r"\bmannequin's\b", "person's", re.sub(r"\bsmooth (?=head\b)", "", text))


def mannequin_paragraph(bundle: dict, colours: dict[str, str]) -> str:
    named = "; ".join(f"{n} is the {c} mannequin" for n, c in colours.items())
    faces = "; ".join(f"image {i}" for i, r in enumerate(bundle["references"], 1) if r["role"] == "face")
    looks = "; ".join(f"image {i}" for i, r in enumerate(bundle["references"], 1) if r["role"] == "look")
    return (f"The approved draft shows every person as a coloured, faceless mannequin: {named}. Replace each mannequin "
            "with that real person, keeping exactly the mannequin's place in the frame, size, seated or standing pose, "
            "hand positions and the direction the head faces (the ridge on the mannequin's head is the nose). Take "
            f"the face, age and hair ONLY from the face sheet ({faces}) and the clothes ONLY from the look sheet "
            f"({looks}). No mannequin, no plastic and none of the mannequin's colour remains anywhere in the frame: "
            "the person has natural skin and real clothes. Nobody looks into the lens unless this shot says so.")


def frame_prompt(bundle: dict, board: dict, shot: int, with_board: bool,
                 colours: dict[str, str] | None = None) -> tuple[str, list[str]]:
    labels = lab.labels(bundle["references"]) + [DRAFT_LABEL] + ([BOARD_LABEL] if with_board else [])
    idx = next(i for i, p in enumerate(board["panels"]) if int(p["shot"]) == shot)
    panel = board["panels"][idx]
    cols, _ = lab.grid_for(len(board["panels"]))
    r, c = divmod(idx, cols)
    parts = [LEAD, *references_block(labels)]
    if colours:
        parts.append(mannequin_paragraph(bundle, colours))
    fix = (lambda t: unmannequin(t, colours)) if colours else (lambda t: t)
    world = scene_world(board["world"])
    if colours:  # the board's sentences about the mannequin treatment itself never reach a frame
        world = " ".join(x for x in re.split(r"(?<=[.!?])\s+", world) if "mannequin" not in x.lower())
    if with_board:
        parts.append(
            f"The storyboard (image {len(labels)}) is the whole scene as {len(board['panels'])} small panels, read "
            f"left to right, top to bottom. This frame is the panel in row {r + 1}, column {c + 1}: the same picture "
            "as the approved draft. Use the other panels only to keep the place, light, colour grade and the fixed "
            "positions of things consistent with the rest of the scene. Paint ONE frame, never a grid.")
    if colours:
        # plan/2026-11-13e §6j: the mannequin writer never describes faces, so a person's STATE (eyes closed, still,
        # not responding) was lost and the frame woke Nimal up. The shot plan's own opening picture carries it, per
        # person and for this shot only (never the scene-wide condition, which holds the whole scene's action).
        plan = next((s for s in bundle["shots"] if int(s["number"]) == shot), {})
        opening = " ".join(str(x).strip() for x in plan.get("opening_picture") or [] if str(x).strip())
        if opening:
            parts.append(f"Each person at the opening of this shot, as planned: {opening} Keep each body exactly as "
                         "flat, bent or upright as its mannequin, and each person's eyes and state exactly as planned.")
    parts += [
        "The scene: " + fix(world),
        fix(f"This shot: {panel['camera'].rstrip('.')}. Background: {panel['background'].rstrip('.')}. "
            f"{panel['picture']}"),
        CLOSE_PLACE,
        CLOSE_SINGLE,
    ]
    return "\n\n".join(parts), labels


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="the storyboard run to paint from, e.g. run_004")
    ap.add_argument("--input", required=True)
    ap.add_argument("--shot", type=int, required=True)
    ap.add_argument("--variants", default="panel,board")
    ap.add_argument("--hypothesis", default="")
    ap.add_argument("--quality", choices=["low", "medium", "high"], default=QUALITY)
    ap.add_argument("--faces", default="", help="people whose face sheet goes first (input/<name>/refs/face_<p>.png)")
    ap.add_argument("--mannequins", action="store_true", help="the board run painted people as mannequins")
    a = ap.parse_args()

    src = HERE / "runs" / a.run
    bundle = json.loads((HERE / "input" / a.input / "bundle.json").read_text(encoding="utf-8"))
    board = json.loads((src / "writer_output.json").read_text(encoding="utf-8"))
    faces = [{"role": "face", "name": n.strip(), "file": f"input/{a.input}/refs/face_{n.strip()}.png"}
             for n in a.faces.split(",") if n.strip()]
    bundle["references"] = faces + bundle["references"]
    colours = lab.mannequin_colours(bundle) if a.mannequins else None
    draft = src / "shots" / f"shot_{a.shot:02d}.png"
    variants = [v.strip() for v in a.variants.split(",") if v.strip()]
    out = lab.next_run()
    print("run:", out.name, "from", a.run, "shot", a.shot, variants)
    oa = lab.client()
    results = []
    for v in variants:
        with_board = v == "board"
        prompt, labels = frame_prompt(bundle, board, a.shot, with_board, colours)
        (out / f"shot{a.shot:02d}_{v}_prompt.txt").write_text(prompt, encoding="utf-8")
        if blocking(prompt):
            print("STOP: the frame prompt has words the image model declines")
            return 1
        files = [(f"reference-{i}.png", (HERE / r["file"]).read_bytes(), "image/png")
                 for i, r in enumerate(bundle["references"], 1)]
        files.append(("draft.png", draft.read_bytes(), "image/png"))
        if with_board:
            files.append(("storyboard.png", (src / "board.png").read_bytes(), "image/png"))
        worst = lab.dollars(lab.IMAGE_MODEL, lab.IMAGE_IN_BASE + lab.IMAGE_IN_PER_REF * len(files), 0,
                            lab.IMAGE_WORST_OUT[a.quality])
        lab.guard(worst, f"frame {v}")
        t0 = time.time()
        img = oa.images.edit(model=lab.IMAGE_MODEL, image=files, prompt=prompt, size=lab.IMAGE_SIZE,
                             quality=a.quality)
        iu = getattr(img, "usage", None)
        usage = {"input": int(getattr(iu, "input_tokens", 0) or 0), "output": int(getattr(iu, "output_tokens", 0) or 0)}
        cost = lab.book(out.name, f"frame-{v}", lab.IMAGE_MODEL, usage, "done", a.hypothesis)
        (out / f"shot{a.shot:02d}_{v}.png").write_bytes(base64.b64decode(img.data[0].b64_json))
        print(f"{v}: {time.time() - t0:.0f}s, {usage}, ${cost:.4f}")
        results.append({"variant": v, "labels": labels, "usage": usage, "usd": round(cost, 4)})
    summary = {"run": out.name, "from": a.run, "shot": a.shot, "quality": a.quality, "hypothesis": a.hypothesis,
               "frames": results, "ledger_usd": round(lab.spent(), 4)}
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
