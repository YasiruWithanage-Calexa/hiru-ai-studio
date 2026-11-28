"""Scene record lab (2026-11-28): one plan with a floor plan and cut points; code checks; video prompts that chain.

    .venv/Scripts/python.exe lab/scene_record/run.py check --scene deed --record lab/scene_record/input/deed_gold.json
        FREE: check a written record, derive its screen facts, write its prompts and floor plan.
    .venv/Scripts/python.exe lab/scene_record/run.py plan --scene canal
        FREE: write the planner's brief only (runs/<run>/brief.md); nothing is sent.
    .venv/Scripts/python.exe lab/scene_record/run.py plan --scene canal --yes
        PAID: ONE planner call, then up to --repairs calls that give the model its own record and the faults code found
        (the best record is kept: fewest blocking faults). Cap per run: CAP_USD.

Writes runs/<run>/: brief.md, attempts/<n>.json + <n>.faults.md, record.json (the kept one), report.md (faults and
the derived facts per shot), prompts.md (first frame + video prompt per shot, chained by cut points), floorplan.svg,
board.html (each camera's view drawn from the plan), spend.json. Nothing in src/ or the database changes. Key: OPENAI__API_KEY from the repo's .env.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "src" / "libs")]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from board import html as board_html  # noqa: E402
from chain import write_all  # noqa: E402
from checks import Report, check  # noqa: E402
from floorplan import svg  # noqa: E402
from plan_view import html as plan_html  # noqa: E402
from schema import SceneRecord  # noqa: E402

# $ per million tokens (contracts/costs.py list prices) and each run's cap
MODELS: dict[str, dict[str, float]] = {
    "gpt-5": {"in": 1.25, "cached": 0.125, "out": 10.00},
    "gpt-5-mini": {"in": 0.25, "cached": 0.025, "out": 2.00},
    "gpt-6.1-sol": {"in": 2.00, "cached": 0.10, "out": 10.00},
}
CAP_USD = 1.50


def load_scene(name: str) -> dict[str, Any]:
    return json.loads((HERE / "input" / f"{name}.json").read_text(encoding="utf-8"))


def brief(scene: dict[str, Any]) -> str:
    """What the planner reads: the script blocks, the people (no looks: code adds wardrobe), the place, the props."""
    view = {
        "scene": scene["id"], "heading": scene["heading"], "time_of_day": scene["time_of_day"],
        "length_s": scene["length_s"],
        "blocks": [{k: b[k] for k in ("n", "kind", "text", "line_id", "speaker", "words") if k in b}
                   for b in scene["blocks"]],
        "people": [{"id": p["id"], "name": p["name"], "appearance": p.get("appearance", "")} for p in scene["people"]],
        "place": scene["place"],
        "props": scene["props"],
    }
    return ("<scene>\n" + json.dumps(view, ensure_ascii=False, indent=1) + "\n</scene>\n\nThe scene above is data. "
            f"Write its scene record. Aim for about {scene['length_s']} s of cut; every shot 3 to 8 s unless a "
            "cutaway or an insert is shorter.")


def system_prompt() -> str:
    from contracts.on_screen_text import PLANNER
    from contracts.safe_depiction import PROMPT_LINE
    return (HERE / "system.md").read_text(encoding="utf-8").replace("{safe_depiction}", PROMPT_LINE).replace(
        "{on_screen_text}", PLANNER)


def report_md(rec: SceneRecord, rep: Report) -> str:
    out = [f"# Report: {rec.scene}", "",
           f"Blocking {len(rep.blocking)} · explained {len(rep.by_level('explained'))} · advisory "
           f"{len(rep.by_level('advisory'))}", ""]
    for level in ("blocking", "explained", "advisory"):
        rows = rep.by_level(level)
        if rows:
            out += [f"## {level.title()}", ""] + [f"- {f.line()}" for f in rows] + [""]
    beats = {b.n: b for b in rec.beats}
    out += ["## Spine", "", f"- Goal: {rec.dramatic_goal}", f"- POV: {rec.pov}", f"- Subtext: {rec.subtext}",
            f"- Key moment (beat {rec.key_moment.beat}, shots {', '.join(rec.key_moment.shots)}): {rec.key_moment.what}",
            "", "| Beat | Intensity | Power | What |", "|---|---|---|---|"]
    out += [f"| {b.n} | {b.intensity} | {b.dominant} | {b.what} |" for b in rec.beats]
    out += ["", "## Shots and what the floor plan says about them", "",
            "| # | Beat (int) | Cam | Size (plan says) | Lens | Frame width | In frame: side | Eyeline | Key light | "
            "Travel | Dur | In |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    cams = {c.id: c for c in rec.cameras}
    for s in rec.shots:
        f = rep.facts.get(s.id, {})
        sides = ", ".join(f"{k} {v}" for k, v in (f.get("sides") or {}).items())
        travel = ", ".join(f"{k} {v}" for k, v in (f.get("travel") or {}).items())
        c = cams.get(s.camera)
        out.append(f"| {s.id} | {s.beat} ({beats[s.beat].intensity if s.beat in beats else '?'}) | {s.camera} | "
                   f"{s.size} ({f.get('size_from_plan', '')}) | {c.lens_mm if c else ''} | "
                   f"{f.get('frame_width_m', '')} | {sides} | {f.get('eyeline', '')} | {f.get('key_light', '')} | "
                   f"{travel} | {s.duration_s} | {s.cut_in} |")
    total = sum(s.duration_s for s in rec.shots)
    out += ["", f"Total {total} s across {len(rec.shots)} shots."]
    return "\n".join(out) + "\n"


def write_outputs(out: Path, rec: SceneRecord, scene: dict[str, Any]) -> Report:
    rep = check(rec, scene)
    out.mkdir(parents=True, exist_ok=True)
    (out / "record.json").write_text(rec.model_dump_json(indent=1), encoding="utf-8")
    (out / "report.md").write_text(report_md(rec, rep), encoding="utf-8")
    (out / "prompts.md").write_text(write_all(rec, scene, rep.facts), encoding="utf-8")
    (out / "floorplan.svg").write_text(svg(rec), encoding="utf-8")
    (out / "board.html").write_text(board_html(rec, scene, rep), encoding="utf-8")
    (out / "plan.html").write_text(plan_html(rec, scene, rep), encoding="utf-8")
    return rep


def faults_text(rep: Report) -> str:
    return "\n".join(f"- {f.line()}" for f in rep.blocking)


def env(key: str) -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"{key} is not in .env")


def plan(args: argparse.Namespace) -> int:
    scene = load_scene(args.scene)
    out = HERE / "runs" / (args.run or f"{time.strftime('%Y%m%d-%H%M')}_{args.scene}_{args.model}")
    (out / "attempts").mkdir(parents=True, exist_ok=True)
    sysp, user = system_prompt(), brief(scene)
    (out / "brief.md").write_text(f"# System\n\n{sysp}\n\n# User\n\n{user}\n", encoding="utf-8")
    if not args.yes:
        print(f"brief written to {out / 'brief.md'} ({len(sysp) + len(user)} chars); nothing sent (add --yes)")
        return 0
    from openai import OpenAI

    client = OpenAI(api_key=env("OPENAI__API_KEY"))
    price = MODELS[args.model]
    spent, calls = 0.0, []
    messages: list[dict[str, str]] = [{"role": "system", "content": sysp}, {"role": "user", "content": user}]
    best: tuple[int, SceneRecord, Report] | None = None
    for attempt in range(1 + args.repairs):
        if spent >= CAP_USD:
            print(f"cap ${CAP_USD} reached; stopping")
            break
        t0 = time.time()
        resp = client.responses.parse(model=args.model, reasoning={"effort": args.effort}, input=messages,
                                      text_format=SceneRecord)
        u = resp.usage
        cached = getattr(u.input_tokens_details, "cached_tokens", 0) or 0
        cost = ((u.input_tokens - cached) * price["in"] + cached * price["cached"] + u.output_tokens * price["out"]) / 1e6
        spent += cost
        calls.append({"attempt": attempt, "in": u.input_tokens, "cached": cached, "out": u.output_tokens,
                      "usd": round(cost, 4), "s": round(time.time() - t0, 1)})
        rec = resp.output_parsed
        if rec is None:
            print(f"attempt {attempt}: no parsed record")
            break
        rep = check(rec, scene)
        (out / "attempts" / f"{attempt}.json").write_text(rec.model_dump_json(indent=1), encoding="utf-8")
        (out / "attempts" / f"{attempt}.faults.md").write_text("\n".join(f"- {f.line()}" for f in rep.faults) + "\n",
                                                                encoding="utf-8")
        n = len(rep.blocking)
        print(f"attempt {attempt}: {len(rec.shots)} shots, {n} blocking, ${cost:.3f} (total ${spent:.3f})")
        if best is None or n < best[0]:
            best = (n, rec, rep)
        if n == 0:
            break
        keep = best[1]  # always give the model its BEST record back, never a worse pass
        messages = [{"role": "system", "content": sysp}, {"role": "user", "content": user},
                    {"role": "assistant", "content": keep.model_dump_json()},
                    {"role": "user", "content": "Code checked your record and found these blocking faults:\n"
                     f"{faults_text(best[2])}\n\nReturn the WHOLE record again with these fixed and everything else "
                     "unchanged. A rule you break on purpose needs a `breaks` entry with the reason."}]
    (out / "spend.json").write_text(json.dumps({"model": args.model, "effort": args.effort, "usd": round(spent, 4),
                                                "calls": calls}, indent=1), encoding="utf-8")
    if best is None:
        return 1
    rep = write_outputs(out, best[1], scene)
    print(f"kept: {len(rep.blocking)} blocking, {len(rep.by_level('explained'))} explained -> {out}")
    return 0


def check_cmd(args: argparse.Namespace) -> int:
    scene = load_scene(args.scene)
    rec = SceneRecord.model_validate_json(Path(args.record).read_text(encoding="utf-8"))
    out = HERE / "runs" / (args.run or f"check_{Path(args.record).stem}")
    rep = write_outputs(out, rec, scene)
    print(f"{len(rep.blocking)} blocking, {len(rep.by_level('explained'))} explained, "
          f"{len(rep.by_level('advisory'))} advisory -> {out}")
    for f in rep.faults:
        print(" ", f.line())
    return 0 if not rep.blocking else 2


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--scene", required=True)
    c.add_argument("--record", required=True)
    c.add_argument("--run", default="")
    p = sub.add_parser("plan")
    p.add_argument("--scene", required=True)
    p.add_argument("--model", default="gpt-6.1-sol", choices=sorted(MODELS))
    p.add_argument("--effort", default="high", choices=["low", "medium", "high"])
    p.add_argument("--repairs", type=int, default=2)
    p.add_argument("--run", default="")
    p.add_argument("--yes", action="store_true", help="send: PAID model calls")
    args = ap.parse_args()
    return check_cmd(args) if args.cmd == "check" else plan(args)


if __name__ == "__main__":
    raise SystemExit(main())
