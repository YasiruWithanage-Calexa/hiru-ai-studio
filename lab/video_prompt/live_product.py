"""plan/2026-11-20b phase 6: the PRODUCT's video prompt agent writes every clip of Api Denna v2 E01-S04.

    .venv/Scripts/python.exe lab/video_prompt/live_product.py            free: the calls it would make
    .venv/Scripts/python.exe lab/video_prompt/live_product.py --yes      PAID: one call a clip (+ one repair at most)
    ... --parts    the clips of lab/line_parts/runs/003_product (plan/2026-11-20: the scene planned in line parts)

The clips are the step's fixtures (`fixtures.py`: the product's clip facts on the lab's world). Each goes through the
same calls `systems/shot_producer/graph.py` makes: the step's brief, `agents.build("video_prompter")`, the gates, ONE
repair, the assembly. Usage comes from the agent's own middleware (the cached tokens show whether the scene, now its
own message, caches). Stops at the cap. Writes runs/<NNN>_product/: prompts.md, spend.json. Nothing in the database.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs"), str(ROOT / "src")]
FIXTURE = ROOT / "src" / "libs" / "hiru_ai" / "steps" / "video_prompt" / "tests" / "fixtures" / "e01_s04.json"
PRICE = {"in": 2.00, "cached": 0.10, "out": 10.00}  # gpt-6.1-sol, $ per million (contracts/costs.py seed, lab run.py)


def dollars(rows: list[dict]) -> float:
    fresh = sum((r["input_tokens"] - r["cached_input_tokens"]) * PRICE["in"] for r in rows)
    rest = sum(r["cached_input_tokens"] * PRICE["cached"] + r["output_tokens"] * PRICE["out"] for r in rows)
    return (fresh + rest) / 1e6


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--cap", type=float, default=0.40)
    ap.add_argument("--parts", action="store_true")
    a = ap.parse_args()
    from hiru_ai.core import agents
    from hiru_ai.core.context import RunContext
    from hiru_ai.core.settings import get_settings
    from hiru_ai.steps.video_prompt import step

    if a.parts:
        sys.path.insert(0, str(HERE))
        from parts_world import parts_data

        data = parts_data()
    else:
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    scene = step.run({"op": "brief", "scene": {"packet": data["packet"], "genre": "", "style_note": ""}})["scene"]
    clips = list(data["clips"].items())
    o = get_settings().openai
    print(f"{len(clips)} clips on {o.model_video_prompter} ({o.effort_video_prompter}); cap ${a.cap:.2f}")
    if not a.yes:
        return
    runs = HERE / "runs"
    n = 1 + max((int(p.name[:3]) for p in runs.iterdir() if p.name[:3].isdigit()), default=0)
    out = runs / f"{n:03d}_product{'_parts' if a.parts else ''}"
    out.mkdir()
    usage: list[dict] = []
    ctx = RunContext(usage_sink=usage.append)
    agent = agents.build("video_prompter")
    title = "E01-S04 in line parts (line_parts run 003)" if a.parts else "E01-S04"
    doc, calls, written = [f"# {title}: video prompts by the product's agent", ""], [], 0
    for slate, clip in clips:
        if dollars(usage) >= a.cap:
            doc.append(f"stopped at the cap: ${dollars(usage):.4f}")
            break
        brief = step.run({"op": "brief", "clip": clip})
        inp = {"scene": scene, "clip": brief["clip"], "cards": brief["cards"]}
        before, started = len(usage), time.monotonic()
        try:
            ans = agent.run(inp, ctx).model_dump(mode="json")
            first = step.run({"op": "check", "direction": ans, "clip": clip})["faults"]
            faults = first
            if faults:
                ans = agent.run({**inp, "repair": faults, "previous": json.dumps(ans, ensure_ascii=False)},
                                ctx).model_dump(mode="json")
                faults = step.run({"op": "check", "direction": ans, "clip": clip})["faults"]
        except Exception as exc:  # the graph writes a warning and no prompt
            first, faults, ans = [], [f"the model call failed: {exc}"], {}
        mine = usage[before:]
        calls.append({"slate": slate, "usage": mine, "usd": round(dollars(mine), 5), "first_faults": first,
                      "faults": faults, "seconds": round(time.monotonic() - started, 1)})
        doc += [f"## {slate} · {clip['sound_mode']} · {clip['take_s']} s · lines "
                f"{', '.join(ln['lid'] for ln in clip['lines']) or 'none'}", ""]
        if faults:
            doc += [f"**No prompt** (the graph warns): {'; '.join(faults)}", ""]
        else:
            written += 1
            made = step.run({"op": "assemble", "direction": ans, "clip": clip, "repaired": bool(first)})
            doc += ["```text", made["prose"], "```", "", "Checks: " + "; ".join(
                f"{c['label']} ({c['tone']})" for c in made["checks"]), ""]
        print(f"{slate}: {len(mine)} call(s), cached {[u['cached_input_tokens'] for u in mine]} of "
              f"{[u['input_tokens'] for u in mine]}, ${dollars(mine):.4f}, "
              f"{'OK' + (' (repaired)' if first else '') if not faults else 'NO PROMPT'}")
    spend = {"usd": round(dollars(usage), 4), "written": written, "clips": len(calls), "calls": calls}
    (out / "spend.json").write_text(json.dumps(spend, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "prompts.md").write_text("\n".join(doc), encoding="utf-8")
    print(f"written {written} of {len(calls)}; spent ${spend['usd']:.4f} -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
