"""The docs point at things that exist, and the pattern doc keeps the plan's eight rules."""
from __future__ import annotations

import re

from hiru_ai.core.registry import PACKAGE_ROOT

REPO = PACKAGE_ROOT.parents[2]
DOCS = [REPO / "docs" / "david" / "README.md", REPO / "docs" / "AI_PATTERN.md",
        REPO / "docs" / "adr" / "0010-one-author-pattern.md"]


def test_the_docs_link_only_to_files_that_exist():
    for doc in DOCS:
        for target in re.findall(r"\]\(([^)#]+)\)", doc.read_text(encoding="utf-8")):
            if target.startswith("http"):
                continue
            if "IMPLEMENTED" in target:
                continue  # written at the end of a phase; the test below says it exists once the work is built
            assert (doc.parent / target).resolve().exists(), f"{doc.name} links to {target}, which does not exist"


def test_the_pattern_has_the_plans_eight_rules_in_order():
    text = (REPO / "docs" / "AI_PATTERN.md").read_text(encoding="utf-8")
    rules = re.findall(r"^(\d)\. \*\*(.+?)\*\*", text, re.M)
    assert [n for n, _ in rules] == [str(n) for n in range(1, 9)]
    assert rules[0][1].startswith("One author") and rules[2][1].startswith("Code judges facts")
    assert "never by adding an agent" in text


def test_the_adr_is_in_the_index():
    assert "0010-one-author-pattern.md" in (REPO / "docs" / "adr" / "README.md").read_text(encoding="utf-8")


def test_every_part_the_readme_names_exists():
    from hiru_ai.core.registry import Registry

    reg = Registry().discover()
    names = set(re.findall(r"`(david_[a-z_]+)`", (REPO / "docs" / "david" / "README.md").read_text(encoding="utf-8")))
    known = {c.manifest.id for c in reg.components.values()}
    assert names and names <= known, sorted(names - known)
