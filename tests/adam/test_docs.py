"""docs/adam/DEVICES.md lists every device of the library, and the docs point at things that exist."""
from __future__ import annotations

import re

from hiru_ai.core.registry import PACKAGE_ROOT

REPO = PACKAGE_ROOT.parents[2]
DEVICES = PACKAGE_ROOT / "knowledge_bases" / "adam" / "adam_film_grammar" / "sources" / "devices"
INDEX = REPO / "docs" / "adam" / "DEVICES.md"


def index_text() -> str:
    rows = []
    for p in sorted(DEVICES.glob("*.md")):
        t = p.read_text(encoding="utf-8")
        title = re.search(r"^# (.+)$", t, re.M).group(1)  # type: ignore[union-attr]
        fields = {m.group(1): m.group(2) for m in re.finditer(r"^\*\*(.+?)\.\*\*\s+(.+?)$", t, re.M)}
        veo = re.match(r"[a-z-]+", fields["Veo feasibility"]).group(0)  # type: ignore[union-attr]
        kind = fields["Allowed kind"].split(" (")[0]
        link = f"../../src/libs/hiru_ai/knowledge_bases/adam/adam_film_grammar/sources/devices/{p.name}"
        rows.append(f"| {p.stem.split('-')[0]} | [{title}]({link}) | {kind} | {veo} |")
    head = INDEX.read_text(encoding="utf-8").split("| # | Device |")[0]
    return head + "| # | Device | Allowed kind | Veo |\n|---|---|---|---|\n" + "\n".join(rows) + "\n"


def write_devices_index() -> None:
    INDEX.write_text(index_text(), encoding="utf-8")


def test_the_device_index_lists_every_device_and_is_current():
    assert INDEX.read_text(encoding="utf-8") == index_text()
    assert INDEX.read_text(encoding="utf-8").count("\n| ") >= 40


def test_the_docs_link_only_to_files_that_exist():
    for doc in (REPO / "docs" / "adam").glob("*.md"):
        for target in re.findall(r"\]\(([^)#]+)\)", doc.read_text(encoding="utf-8")):
            if target.startswith("http"):
                continue
            assert (doc.parent / target).resolve().exists(), f"{doc.name} links to {target}"
