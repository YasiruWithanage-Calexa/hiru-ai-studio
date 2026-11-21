"""This lab's two wallets (the person's caps, 2026-11-20): OpenAI $1.50 (runs/spend_total.json) and Omni $2.00
(runs/omni_total.json, counted at the 720p ceiling rate). Every paid call asks first with its worst case."""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAPS = {"openai": 1.50, "omni": 2.00}
FILES = {"openai": HERE / "runs" / "spend_total.json", "omni": HERE / "runs" / "omni_total.json"}


class Wallet:
    def __init__(self, kind: str = "openai") -> None:
        self.kind, self.cap, self.file = kind, CAPS[kind], FILES[kind]
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.data = json.loads(self.file.read_text(encoding="utf-8")) if self.file.exists() else {"usd": 0.0,
                                                                                                    "calls": []}

    def allow_usd(self, worst: float, what: str) -> bool:
        ok = self.data["usd"] + worst <= self.cap + 1e-9
        print(f"  {self.kind} wallet: ${self.data['usd']:.4f} spent; {what} at worst ${worst:.3f}; cap "
              f"${self.cap:.2f}{'' if ok else ' -> REFUSED'}")
        return ok

    def add_usd(self, what: str, usd: float, detail: dict | None = None) -> None:
        self.data["usd"] = round(self.data["usd"] + usd, 5)
        self.data["calls"].append({"what": what, "usd": round(usd, 5), **({"detail": detail} if detail else {})})
        self.file.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
