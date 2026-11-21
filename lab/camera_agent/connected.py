"""Raphael + Camera agent, connected as planned for the product (2026-11-20): a FRESH Raphael run on a scene (the
product's raphael_shot_planner on the packet path, both stages, via lab/two_memories `raphael_one`), then the Camera
agent on THAT result. No video, nothing written to the database.

    .venv/Scripts/python.exe lab/camera_agent/connected.py              dry: the plan and the caps, nothing sent
    .venv/Scripts/python.exe lab/camera_agent/connected.py --yes        PAID: Raphael (cap $0.30) then the Camera agent

Money: the lab's wallet (runs/spend_total.json, cap $1.00). Raphael runs only when its cap plus the Camera agent's
worst case still fit; its spend is entered in the wallet. Writes runs/connected_<scene>/: 12_raphael/<scene>.json and
.txt (Raphael's own), then the Camera agent's brief.txt, answer.json, report.md.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "lab" / "llm_reader"), str(ROOT / "src" / "libs"), str(ROOT / "src"), str(ROOT / "lab")]

RAPHAEL_CAP_USD = 0.30
CAMERA_WORST_USD = 0.19  # run.py MAX_OUT 16k output + ~15k input at gpt-6.1-sol prices
WALLET = HERE / "runs" / "spend_total.json"
PACKETS = ROOT / "lab" / "llm_reader" / "runs" / "e2e" / "05_packets.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="E01-S04")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    out = HERE / "runs" / f"connected_{args.scene}"
    (out / "12_raphael").mkdir(parents=True, exist_ok=True)
    wallet = json.loads(WALLET.read_text(encoding="utf-8"))
    worst = wallet["usd"] + RAPHAEL_CAP_USD + CAMERA_WORST_USD
    print(f"{args.scene}: Raphael (cap ${RAPHAEL_CAP_USD:.2f}) then the Camera agent (worst ${CAMERA_WORST_USD:.2f}); "
          f"lab spent ${wallet['usd']:.4f}; worst total ${worst:.3f} of $1.00")
    saved = out / "12_raphael" / f"{args.scene}.json"
    if not args.yes:
        print("dry: nothing sent (add --yes)")
        return 0
    if not saved.exists():
        if worst > 1.00 + 1e-9:
            print("refused: past the lab's cap")
            return 1
        from cinematic.run import load_env
        from hiru_ai.core.settings import get_settings

        load_env()
        os.environ["RAPHAEL_SCENE_CAP_USD"] = str(RAPHAEL_CAP_USD)
        get_settings.cache_clear()
        from two_memories.live import raphael_one

        packet = json.loads(PACKETS.read_text(encoding="utf-8"))[args.scene]
        s = raphael_one(out, args.scene, packet, int(args.scene[-2:]))
        wallet["usd"] = round(wallet["usd"] + s["dollars"], 5)
        wallet["calls"].append({"what": f"{args.scene} raphael (connected)", "usage": {"calls": s["calls"]},
                                "usd": s["dollars"]})
        WALLET.write_text(json.dumps(wallet, indent=1), encoding="utf-8")
        if s["status"] != "done":
            print(f"Raphael did not finish: {s['status']}")
            return 1
    else:
        print(f"Raphael already ran: {saved}")
    return subprocess.call([sys.executable, str(HERE / "run.py"), "--scene", args.scene, "--raphael", str(saved),
                            "--out", f"connected_{args.scene}", "--yes"])


if __name__ == "__main__":
    raise SystemExit(main())
