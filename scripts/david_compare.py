"""The blind comparison of plan/2026-11-05e §9 (Phase 6), and the plain shot lists the spike shows beside ChatGPT (D10).

    python scripts/david_compare.py --scene phone_call            # builds the lists and the page for one scene
    python scripts/david_compare.py                               # every scene that has a David plan saved

For each scene it writes, under `tests/eval/david/compare/<scene>/`, one plain shot list per contestant that exists:

    david.txt     the plan David saved (`tests/eval/david/spike/<config>/<scene>.json`, the config named by `--config`)
    adam.txt      the plan Adam saved (`tests/eval/adam/live/<scene>.json`), when it has one
    classic.txt   the classic planner's baseline (`tests/eval/adam/baselines/<scene>.yaml`)
    chatgpt.txt   what a person pasted from ChatGPT (`tests/eval/david/chatgpt/<scene>.txt`), as it is

then `blind.html`, a page for a Hiru director with the lists under shuffled letters and a form (rank them; 1 to 5 on
"I can see the scene", "the feeling lands", "it cuts well", "it is filmable in Veo"), and `key.json`,
which letter is which.
The
page names nobody. Beside it, from code and never in the interface: fidelity breaks, overruns, unbound lines, staging
findings, calls, cost and time are in the spike's output.

A shot list is plain: size, take, the picture, the lines (who, and their words from the script), the sound. No camera
jargon and no field names, so a director reads a plan and not a format. Nothing here calls a model.
"""
from __future__ import annotations

import argparse
import html
import json
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "libs"))
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

EVAL = ROOT / "tests" / "eval" / "david"
COMPARE = EVAL / "compare"
CHATGPT = EVAL / "chatgpt"
SPIKE = EVAL / "spike"
ADAM_EVAL = ROOT / "tests" / "eval" / "adam"
QUESTIONS = ("I can see the scene", "the feeling lands", "it cuts well", "it is filmable in Veo")
SIZES = {"WIDE": "wide", "MS": "medium", "MCU": "medium close-up", "CU": "close-up", "TWO": "two-shot",
         "OTS": "over the shoulder", "INSERT": "insert"}


def words_of(scene: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """line id → (speaker, the line's words) from the scene's blocks."""
    return {b["line_id"]: (b.get("speaker", ""), b["text"]) for b in scene["blocks"] if b.get("line_id")}


def picture_of(shot: dict[str, Any]) -> str:
    """What the shot shows, in the author's own words: the action of its first beat, else why it is there."""
    for beat in shot["ir"].get("beats") or []:
        if isinstance(beat, dict) and str(beat.get("action") or "").strip():
            return str(beat["action"]).strip()
    return str(shot["why"]).strip()


def from_david(stored: dict[str, Any], scene: dict[str, Any]) -> str:
    """David's plan as a plain list."""
    said = words_of(scene)
    out = []
    for s in stored["plan"]["shots"]:
        lines = [f'{said[ln][0]}: "{said[ln][1]}"' for ln in s["lines"] if ln in said]
        sound = ", ".join(x for x in (s["sound"]["ambience"], s["sound"]["effects"], s["sound"]["music"]) if x)
        bits = [f"{s['n']}. {SIZES.get(s['size'], s['size'])}, {s['take_s']} s: {picture_of(s)}"]
        if s["over"]:
            bits.append(f"(the picture stays on {s['over']} while the line is heard)")
        if lines:
            bits.append("  Says: " + " / ".join(lines))
        if s["sound"]["silence"]:
            bits.append("  Silence.")
        elif sound:
            bits.append(f"  Sound: {sound}")
        out.append("\n".join(bits))
    return "\n\n".join(out)


def from_adam(stored: dict[str, Any], scene: dict[str, Any]) -> str:
    """Adam's plan (a saved live run, `StoredPlan` data) as a plain list."""
    said = words_of(scene)
    moments = {m["id"]: m for m in stored.get("moments") or []}
    out = []
    for c in stored.get("cards") or []:
        seen = "; ".join(moments[i]["seen"] for i in c["moments"] if i in moments and moments[i].get("seen"))
        lines = [f'{said[cl["line_id"]][0]}: "{said[cl["line_id"]][1]}"' for cl in c.get("lines") or []
                 if cl["line_id"] in said]
        sound = ", ".join(x for x in ((c.get("sound") or {}).get(k, "") for k in ("ambience", "effects", "music")) if x)
        bits = [f"{c['number']}. {c['size'].lower()}, {c['take_s']} s: {seen or c.get('title', '')}"]
        if lines:
            bits.append("  Says: " + " / ".join(lines))
        if (c.get("sound") or {}).get("silence"):
            bits.append("  Silence.")
        elif sound:
            bits.append(f"  Sound: {sound}")
        out.append("\n".join(bits))
    return "\n\n".join(out)


def from_classic(shots: list[dict[str, Any]], scene: dict[str, Any]) -> str:
    """The classic planner's baseline (`tests/eval/adam/baselines`, `script_split` rows) as a plain list."""
    blocks = {b["index"]: b for b in scene["blocks"]}
    out = []
    for s in shots:
        picked = [blocks[i] for i in range(int(s.get("block_start", 0)), int(s.get("block_end", 0))) if i in blocks]
        action = " ".join(b["text"] for b in picked if b["kind"] != "dialogue") or s.get("title", "")
        lines = [f'{b["speaker"]}: "{b["text"]}"' for b in picked if b["kind"] == "dialogue"]
        size = str(s.get("framing"))
        bit = f"{s['number']}. {SIZES.get(size, size.lower())}, {s['duration_s']} s: {action}"
        out.append(bit + ("\n  Says: " + " / ".join(lines) if lines else ""))
    return "\n\n".join(out)


def blind_page(scene: str, lists: dict[str, str], seed: int = 0) -> tuple[str, dict[str, str]]:
    """-> (the page, the key: letter → contestant). The letters are shuffled; the page names nobody."""
    names = sorted(lists)
    shuffled = list(names)
    random.Random(f"{scene}:{seed}").shuffle(shuffled)  # noqa: S311  (a letter order, not a secret)
    key = {chr(ord("A") + n): name for n, name in enumerate(shuffled)}
    boxes = "\n".join(f"<section><h2>Plan {letter}</h2><pre>{html.escape(lists[name])}</pre></section>"
                      for letter, name in key.items())
    rows = "\n".join(f"<tr><th>{html.escape(q)}</th>" + "".join(
        f'<td><input type="number" min="1" max="5" name="{letter}-{n}" aria-label="Plan {letter}: {html.escape(q)}">'
        "</td>" for letter in key) + "</tr>" for n, q in enumerate(QUESTIONS))
    head = "".join(f"<th>Plan {letter}</th>" for letter in key)
    ranks = " ".join(f'<label>Plan {letter} <input type="number" min="1" max="{len(key)}" name="rank-{letter}"></label>'
                     for letter in key)
    title = html.escape(scene)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}: which plan?</title>
<style>body{{font:16px/1.5 system-ui;max-width:60rem;margin:2rem auto;padding:0 1rem}}pre{{white-space:pre-wrap}}
section{{border:1px solid #8884;border-radius:.5rem;padding:0 1rem;margin:1rem 0}}
td,th{{padding:.3rem .6rem}}</style></head>
<body><h1>{html.escape(scene)}</h1>
<p>Read the {len(key)} plans for the same scene. Rank them from best (1) to worst, then give each 1 to 5 on the four
questions. Nobody is named; the letters are shuffled.</p>
{boxes}
<form><h2>Rank</h2><p>{ranks}</p>
<h2>Score</h2><table><tr><th></th>{head}</tr>{rows}</table></form></body></html>
"""
    return page, key


def lists_for(scene_name: str, config: str) -> dict[str, str]:
    scene = yaml.safe_load((EVAL / "scenes" / f"{scene_name}.yaml").read_text(encoding="utf-8"))["scene"]
    lists: dict[str, str] = {}
    david = SPIKE / config / f"{scene_name}.json"
    if david.exists():
        lists["david"] = from_david(json.loads(david.read_text(encoding="utf-8")), scene)
    adam = ADAM_EVAL / "live" / f"{scene_name}.json"
    if adam.exists():
        lists["adam"] = from_adam(json.loads(adam.read_text(encoding="utf-8")), scene)
    base = ADAM_EVAL / "baselines" / f"{scene_name}.yaml"
    if base.exists():
        lists["classic"] = from_classic(yaml.safe_load(base.read_text(encoding="utf-8"))["shots"], scene)
    pasted = CHATGPT / f"{scene_name}.txt"
    if pasted.exists():
        lists["chatgpt"] = pasted.read_text(encoding="utf-8").strip()
    return lists


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--scene", action="append", help="a scene (default: every scene David has a saved plan for)")
    ap.add_argument("--config", default="A", help="which spike configuration is David's (default A)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    names = args.scene or sorted(p.stem for p in (SPIKE / args.config).glob("*.json") if "." not in p.stem)
    if not names:
        print(f"No David plan saved under {SPIKE / args.config}: run scripts/david_spike.py first.")
        return 1
    for name in names:
        lists = lists_for(name, args.config)
        if len(lists) < 2:
            print(f"{name}: only {sorted(lists)} to read; a comparison needs two or more. Paste ChatGPT's answer into "
                  f"{CHATGPT / (name + '.txt')} or run the other planners.")
            continue
        folder = COMPARE / name
        folder.mkdir(parents=True, exist_ok=True)
        for who, text in lists.items():
            (folder / f"{who}.txt").write_text(text + "\n", encoding="utf-8")
        page, key = blind_page(name, lists, args.seed)
        (folder / "blind.html").write_text(page, encoding="utf-8")
        (folder / "key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
        print(f"{name}: {len(lists)} plans ({', '.join(sorted(lists))}) -> {folder / 'blind.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
