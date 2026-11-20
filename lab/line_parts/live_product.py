"""plan/2026-11-20 phase 8.1: the PRODUCT's Raphael plans Api Denna v2 E01-S04 with its long lines in parts.

    .venv/Scripts/python.exe lab/line_parts/live_product.py            free: what Raphael would be given
    .venv/Scripts/python.exe lab/line_parts/live_product.py --yes      PAID: one scene, capped by RAPHAEL_SCENE_CAP_USD

Unlike run.py, nothing here is patched: the clock, the split, H-17 and the checks are src/'s. The scene is the saved
packet of lab/llm_reader/runs/e2e (its line rows made from it, as the breakdown fills them); the result is written as
rows by `raphael_write` IN MEMORY and saved under runs/<NNN>_product/. Nothing is written to the database.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs"), str(ROOT / "src")]
E2E = ROOT / "lab" / "llm_reader" / "runs" / "e2e"
SID = "E01-S04"
TAKES = [4, 6, 8, 10, 15]


def rows(packet: dict) -> tuple[dict, list[dict]]:
    script, lines = [], []
    for b in packet["E_blocks"]:
        if b["kind"] == "dialogue" and b.get("speaker"):
            lines.append({"id": b["id"], "production_id": "p", "scene_id": SID, "ord": len(lines),
                          "speaker": b["speaker"], "character_id": None, "text": b["text"], "delivery": ""})
            script.append({"kind": "dialogue", "line_id": b["id"]})
        else:
            script.append({"kind": "action", "text": b["text"], "by": "person"})
    scene = {"id": SID, "production_id": "p", "number": 4, "script": script, "script_version": 1, "status": "draft",
             "envelope_s": packet["H_length"]["stated_seconds"], "line_parts": False}
    return scene, lines


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--cap", type=float, default=0.40)
    a = ap.parse_args()
    os.environ["RAPHAEL_SCENE_CAP_USD"] = str(a.cap)
    from hiru_ai.core.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    from hiru_ai.core.context import RunContext
    from hiru_ai.steps.raphael.raphael_write import logic as write
    from hiru_ai.systems.raphael.raphael_shot_planner import scene as raphael

    packet = json.loads((E2E / "05_packets.json").read_text(encoding="utf-8"))[SID]
    scene_row, lines = rows(packet)
    made = raphael.from_packet(packet, lines, TAKES, settings.raphael_line_parts)
    assert made is not None, "the packet does not pair with its lines"
    opening, script, line_ids = made
    parts = sum(b.is_part for b in script.blocks)
    print(f"RAPHAEL_LINE_PARTS={settings.raphael_line_parts}; {len(script.blocks)} blocks, {parts} of them parts; "
          f"cap ${a.cap:.2f}")
    if not a.yes:
        print(opening[opening.index("<timing>"):opening.index("</timing>") + 9])
        return
    runs = HERE / "runs"
    n = 1 + max((int(p.name[:3]) for p in runs.iterdir() if p.name[:3].isdigit()), default=0)
    out = runs / f"{n:03d}_product"
    out.mkdir()
    (out / "opening.txt").write_text(opening, encoding="utf-8")
    planner = raphael.Planner(RunContext(), script, number=4, line_ids=line_ids, production={}, context={},
                              opening=opening)
    started = time.monotonic()
    try:
        stored = planner.plan(previous={}, job_id=f"live-parts-{n}").stored
        status = "done"
    except raphael.Failed as exc:
        stored, status = None, f"failed: {exc}"
    spend = {"status": status, "calls": planner.meter.calls, "usd": round(planner.meter.spent, 4),
             "seconds": round(time.monotonic() - started)}
    (out / "spend.json").write_text(json.dumps(spend, indent=1), encoding="utf-8")
    print(spend)
    if stored is None:
        return
    (out / "result.json").write_text(json.dumps(stored.data(), ensure_ascii=False, indent=1), encoding="utf-8")
    production = {"id": "p", "title": "Api Denna", "orientation": "horizontal",
                  "settings": {"max_take_s": 15, "take_lengths": "steps"}}
    shots, line_rows, fields = write.write(scene_row, lines, stored, [], production)
    (out / "rows.json").write_text(json.dumps({"shots": shots, "lines": line_rows, "fields": {
        k: v for k, v in fields.items() if k != "raphael"}}, ensure_ascii=False, indent=1, default=str),
                                   encoding="utf-8")
    report = [f"stage1 {stored.stage1}, stage2 {stored.stage2}, line_parts {stored.line_parts}, "
              f"scene field line_parts={fields.get('line_parts')}", f"left: {[(x.code, x.fix) for x in stored.left]}"]
    for s in shots:
        clip = next(c for c in stored.clips if c.slate == s["slate"])
        carried = [f"{lid}{'' if not script.block(int(lid[1:])) or not script.block(int(lid[1:])).is_part else ' p' + str(script.block(int(lid[1:])).part) + '/' + str(script.block(int(lid[1:])).parts)}"
                   for lid in clip.lines]
        report.append(f"S{s['number']:02d} {s['slate']:6} {clip.priority:6} {clip.size:5} setup {clip.setup} "
                      f"{clip.take_s:>2} s {s['sound_mode']:9} speaks={clip.speaks} lines {carried}")
    for r in line_rows:
        report.append(f"line {r['id']}: shot {next((x['slate'] for x in shots if x['id'] == r['shot_id']), '-')}, "
                      f"overrun {r['overrun_s']}")
    (out / "report.txt").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))
    print(f"written: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
