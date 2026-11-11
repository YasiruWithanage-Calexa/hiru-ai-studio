"""Writes `runs/compare_ekama.md`: for each scene, what Raphael is sent today and our packet, side by side (no model)."""
from __future__ import annotations

import sys

sys.path[:0] = ["lab", "src", "src/libs"]
from two_memories import compare, packet, render, stage_run  # noqa: E402


def main(scenes: list[int]) -> str:
    bd, _d, cont = stage_run.load()
    out = ["# Raphael today and the scene packet, side by side (Ekama, no model)", ""]
    for n in scenes:
        sid = f"E01-S{n:02d}"
        out += [f"## Scene {n}", "", "### Raphael is sent today", "", "```", compare.today(n), "```", "",
                "### Our packet (rendered as text)", "", "```", render.render(packet.assemble(bd, sid, cont)), "```", ""]
    return "\n".join(out)


if __name__ == "__main__":
    text = main([int(x) for x in sys.argv[1:]] or [2, 3, 8])
    open("lab/two_memories/runs/compare_ekama.md", "w", encoding="utf-8").write(text)
    print(len(text), "chars written")
