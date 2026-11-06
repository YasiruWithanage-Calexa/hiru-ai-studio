"""The blind comparison of plan/2026-11-06b §8 (the gate): Jonathan's plan beside the other planners and ChatGPT.

    python scripts/jonathan_compare.py --scene phone_call            # the page for one scene (the latest run)
    python scripts/jonathan_compare.py --scene phone_call --run 2    # a given run of the trial
    python scripts/jonathan_compare.py                               # every scene the trial saved a plan for

For each scene it writes, under `tests/eval/jonathan/compare/<scene>/`, one plain shot list per contestant that exists:

    jonathan.txt  the plan the trial saved (`tests/eval/jonathan/spike/<scene>/<run>.json`)
    adam.txt      the plan Adam saved (`tests/eval/adam/live/<scene>.json`), when it has one
    classic.txt   the classic planner's baseline (`tests/eval/adam/baselines/<scene>.yaml`)
    chatgpt.txt   what a person pasted from ChatGPT (`tests/eval/jonathan/chatgpt/<scene>.txt`), as it is

then `blind.html`, a page for a Hiru director with the lists under shuffled letters and a form (rank them; 1 to 5 on
"I can see the scene", "the feeling lands", "it cuts well", "it is filmable in Veo"), and `key.json`, which letter is
which. The page names nobody. Calls, cost and time are in the trial's output, never on the page.

Jonathan's list is the cinematic lab's shot card for every shot (the size, the take and what the edit keeps, the camera,
each visual beat, the purpose, the line in the script's words, the sound), under its sequence: the lab's first blind
read printed less of one plan than of another and so judged the page, not the plans. Nothing here calls a model.
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

EVAL = ROOT / "tests" / "eval" / "jonathan"
COMPARE = EVAL / "compare"
CHATGPT = EVAL / "chatgpt"
SPIKE = EVAL / "spike"
ADAM_EVAL = ROOT / "tests" / "eval" / "adam"
QUESTIONS = ("I can see the scene", "the feeling lands", "it cuts well", "it is filmable in Veo")
SIZES = {"EWS": "extreme wide", "WIDE": "wide", "MWS": "medium wide", "MS": "medium", "MCU": "medium close-up",
         "CU": "close-up", "ECU": "extreme close-up", "TWO": "two-shot", "OTS": "over the shoulder", "INSERT": "insert",
         "POV": "point of view"}


def words_of(scene: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """line id → (speaker, the line's words) from the scene's blocks."""
    return {b["line_id"]: (b.get("speaker", ""), b["text"]) for b in scene["blocks"] if b.get("line_id")}


def picture_of(shot: dict[str, Any]) -> str:
    """What the shot shows, in the author's own words: the action of its first beat, else why it is there."""
    for beat in shot["ir"].get("beats") or []:
        if isinstance(beat, dict) and str(beat.get("action") or "").strip():
            return str(beat["action"]).strip()
    return str(shot["why"]).strip()


def shot_card(shot: dict[str, Any], said: dict[str, tuple[str, str]]) -> str:
    """One shot as a professional shot-list entry (the cinematic lab's `shot_card`): the size and the take (and what the
    edit keeps), the camera, every visual beat, the purpose, the line and the sound."""
    ir = shot.get("ir") or {}
    cin = ir.get("cinematography") or {}
    sound = shot.get("sound") or {}
    keeps = shot.get("use_s")
    head = f"SHOT {int(shot['n']):02d} — {SIZES.get(shot['size'], shot['size'])}, {shot['take_s']} s" + (
        f" (keeps {keeps} s)" if keeps and keeps != shot["take_s"] else "")
    rows = [head, "  Camera: " + " · ".join(str(x) for x in (shot.get("angle") or cin.get("angle"),
                                                             shot.get("lens") or cin.get("camera"),
                                                             cin.get("movement")) if x)]
    for beat in ir.get("beats") or []:
        if isinstance(beat, dict) and str(beat.get("action") or "").strip():
            note = "; ".join(str(beat[k]).strip() for k in ("camera", "performance") if str(beat.get(k) or "").strip())
            seen = f"  Visual {beat.get('time', '')}: {str(beat['action']).strip()}"
            rows.append(seen + (f" ({note})" if note else ""))
    rows.append(f"  Purpose: {shot.get('why', '')}")
    if shot.get("over"):
        rows.append(f"  (the picture stays on {shot['over']} while the line is heard)")
    lines = [f'{said[ln][0]}: "{said[ln][1]}"' for ln in shot.get("lines") or [] if ln in said]
    if lines:
        rows.append("  Says: " + " / ".join(lines))
    heard = ", ".join(x for x in (sound.get("ambience"), sound.get("effects"), sound.get("music")) if x)
    rows.append("  Audio: silence" if sound.get("silence") else (f"  Audio: {heard}" if heard else ""))
    return "\n".join(r for r in rows if r)


def from_jonathan(stored: dict[str, Any], scene: dict[str, Any]) -> str:
    """Jonathan's plan as a shot list: each sequence's title and purpose, then its shots as full shot cards."""
    said = words_of(scene)
    plan = stored["plan"]
    out = []
    for q in plan.get("sequences") or []:
        out.append(f"{q['id']}. {str(q['title']).upper()}: {q['purpose']}")
        out += [shot_card(s, said) for s in plan["shots"] if s.get("sequence") == q["id"]]
        out.append("")
    return "\n\n".join(out).strip()


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


def saved_run(scene_name: str, run: int | None) -> Path:
    """The trial's saved plan for a scene: run `run`, or the latest."""
    if run is not None:
        return SPIKE / scene_name / f"{run}.json"
    runs = sorted((p for p in (SPIKE / scene_name).glob("*.json") if p.stem.isdigit()), key=lambda p: int(p.stem))
    return runs[-1] if runs else SPIKE / scene_name / "1.json"


def scene_of(scene_name: str, scene_file: str | None) -> dict[str, Any]:
    path = Path(scene_file) if scene_file else EVAL / "scenes" / f"{scene_name}.yaml"
    return dict(yaml.safe_load(path.read_text(encoding="utf-8"))["scene"])


def lists_for(scene_name: str, run: int | None = None, scene_file: str | None = None) -> dict[str, str]:
    scene = scene_of(scene_name, scene_file)
    lists: dict[str, str] = {}
    jonathan = saved_run(scene_name, run)
    if jonathan.exists():
        lists["jonathan"] = from_jonathan(json.loads(jonathan.read_text(encoding="utf-8")), scene)
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
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--scene", action="append", help="a scene (default: every scene the trial saved a plan for)")
    ap.add_argument("--run", type=int, help="which of the trial's runs is Jonathan's (default: the latest)")
    ap.add_argument("--scene-file", help="the scene's yaml, when it is not a gold scene (the lab's shape)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    names = args.scene or sorted(p.name for p in SPIKE.glob("*/") if any(p.glob("*.json")))
    if not names:
        print(f"No Jonathan plan saved under {SPIKE}: run scripts/jonathan_spike.py first.")
        return 1
    for name in names:
        lists = lists_for(name, args.run, args.scene_file)
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
