"""Plan the written chase scene (story/chase_packet.json) with the product's Raphael, both stages, on the packet path
(lab/two_memories `raphael_one`, as raphael_shot_planner runs it). No database.

    .venv/Scripts/python.exe lab/camera_moves/chase.py            dry: the cap and the wallet
    .venv/Scripts/python.exe lab/camera_moves/chase.py --yes      PAID: Raphael on E09-S01 (cap $0.33)

Money: this lab's wallet (runs/spend_total.json, $1.50 OpenAI, the person's, 2026-11-20).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "lab" / "llm_reader"), str(ROOT / "src" / "libs"), str(ROOT / "src"), str(ROOT / "lab")]

from wallet import Wallet  # noqa: E402

RAPHAEL_CAP_USD = 0.33
SID = "E09-S01"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    out = HERE / "runs" / "chase_raphael"
    (out / "12_raphael").mkdir(parents=True, exist_ok=True)
    wallet = Wallet()
    if (out / "12_raphael" / f"{SID}.json").exists():
        print("already planned")
        return 0
    if not wallet.allow_usd(RAPHAEL_CAP_USD, "Raphael on the chase") or not args.yes:
        return 0
    from cinematic.run import load_env
    from hiru_ai.core.settings import get_settings

    load_env()
    os.environ["RAPHAEL_SCENE_CAP_USD"] = str(RAPHAEL_CAP_USD)
    get_settings.cache_clear()
    from two_memories.live import raphael_one

    packet = json.loads((HERE / "story" / "chase_packet.json").read_text(encoding="utf-8"))[SID]
    s = raphael_one(out, SID, packet, 1)
    wallet.add_usd(f"{SID} raphael", s["dollars"], {"calls": s["calls"], "seconds": s["seconds"]})
    print(f"Raphael: {s['status']}; lab total ${wallet.data['usd']:.4f}")
    return 0 if s["status"] == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
