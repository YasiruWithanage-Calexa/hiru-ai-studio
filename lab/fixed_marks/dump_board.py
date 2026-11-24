"""Save a scene board version's parts as they were painted (read-only: GET requests only): each part's prompt, the
pictures its prompt names (in order), its painted picture, and the writer's spots and plates.

    .venv/Scripts/python.exe lab/fixed_marks/dump_board.py [version]      (default: the newest version)

Writes `lab/fixed_marks/board_v<N>/`.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "src" / "libs")]

import fetch  # noqa: E402

from contracts import board as kit  # noqa: E402
from contracts.canon import views_asset  # noqa: E402
from contracts.frame_brief import sheet_path  # noqa: E402


def main() -> int:
    rows = fetch.rows("scene_boards", scene_id=f"eq.{fetch.SCENE}", select="*", order="version.desc,part.asc")
    version = int(sys.argv[1]) if len(sys.argv) > 1 else rows[0]["version"]
    parts = [r for r in rows if r["version"] == version]
    out = HERE / f"board_v{version}"
    out.mkdir(exist_ok=True)
    canon = fetch.rows("canon_entities", production_id=f"eq.{fetch.PROD}",
                       select="id,name,kind,current:canon_versions!canon_entities_current_version_fkey(*)")
    summary = []
    for r in parts:
        n = r["part"]
        prompt = r.get("prompt") or ""
        (out / f"part{n}_prompt.txt").write_text(prompt, encoding="utf-8")
        if r.get("storage_path"):
            (out / f"part{n}_board.png").write_bytes(fetch.file("frames", r["storage_path"]))
        head = prompt.split("Reference images, in order:", 1)
        labels = re.findall(r"[Ii]mage \d+ is (.+?)(?=, numbered|\. Take|; image|\.\s)", head[1]) if len(head) == 2 else []
        pictures = []
        for i, label in enumerate(labels, 1):
            name = f"part{n}_ref{i}.png"
            try:
                if label.startswith(kit.OVERLAP_LABEL):
                    prev = next(p for p in parts if p["part"] == n - 1)
                    last = max((c for c in prev["cells"] if c.get("panel") and c.get("path")), key=lambda c: c["panel"])
                    data = fetch.file("frames", last["path"])
                elif label.startswith("the blocking plate for "):
                    plate = next(x for x in (r.get("writer") or {}).get("plates") or [])
                    data = fetch.file("frames", plate["path"])
                else:
                    row = next(c for c in canon if label.split(":")[0].split(" for ", 1)[-1].startswith(c["name"]))
                    asset = views_asset(row)
                    data = fetch.file("references", str(asset["path"]) if asset and "sheet" in label else sheet_path(row))
                (out / name).write_bytes(data)
            except Exception as exc:  # noqa: BLE001
                name = f"(not read: {exc})"
            pictures.append({"image": i, "label": label, "file": name})
        summary.append({"part": n, "status": r["status"], "pictures": pictures,
                        "ground_marks_paragraphs": prompt.count("Ground marks ("),
                        "panel_marks_lines": prompt.count("— Marks:")})
    writer = (parts[0].get("writer") or {})
    (out / "writer_marks_and_plates.json").write_text(json.dumps(
        {"marks": writer.get("marks"), "plates": writer.get("plates"), "conflicts": writer.get("conflicts")},
        ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
