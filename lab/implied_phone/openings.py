"""Render Raphael's stage-1 opening for both packets (no model call) so the change can be read."""
import json, sys
from pathlib import Path
sys.path[:0] = ["src/libs", "src/services"]
from contracts.raphael.packet import opening
HERE = Path(__file__).parent
for name in ("base", "phone"):
    ps = json.loads((HERE / name / "09_packets.json").read_text(encoding="utf-8"))
    for sid, p in ps.items():
        (HERE / name / "opening.txt").write_text(opening(p)[0], encoding="utf-8")
