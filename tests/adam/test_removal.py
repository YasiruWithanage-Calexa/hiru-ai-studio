"""Plan/2026-11-04b §5.0 rule 6: deleting the `adam` folders removes Adam. The list below is the plan's, word for word;
`hiru-ai remove --group adam` must know every folder on it (the ones that exist today are deleted, the rest are on its
list for when they are made)."""
from __future__ import annotations

from hiru_ai.cli.tools import group_folders, remove_group
from hiru_ai.core import manifest as mf
from hiru_ai.core.registry import PACKAGE_ROOT, Registry

REPO = PACKAGE_ROOT.parents[2]

# rule 6: "the six hiru_ai/<layer>/adam/ folders, contracts/adam/, services/shot_planner_adam/, tests/adam/,
# tests/eval/adam/, docs/adam/" (and the interface's features/adam/, which is in another repository)
THE_PLAN_REMOVES = {
    *(f"src/libs/hiru_ai/{layer}/adam" for layer in mf.LAYERS.values()),
    "src/libs/contracts/adam",
    "src/services/shot_planner_adam",
    "tests/adam",
    "tests/eval/adam",
    "docs/adam",
}


def test_the_removal_list_is_the_plans_list():
    reg = Registry().discover()
    declared = {f"src/libs/hiru_ai/{layer}/adam" for layer in mf.LAYERS.values() if (layer, "adam") in reg.groups}
    for key, group in reg.groups.items():
        if key[1] == "adam":
            declared.update(group.folders)
    assert declared == THE_PLAN_REMOVES


def test_remove_group_on_the_real_tree_is_a_dry_run_that_lists_the_folders_that_exist():
    reg = Registry().discover()
    lines = remove_group(reg, "adam", yes=False)
    deletions = {line.removeprefix("would delete ") for line in lines if line.startswith("would delete ")}
    existing = {rel for rel in THE_PLAN_REMOVES if (REPO / rel).exists()}
    assert deletions == existing
    assert {str(f.relative_to(REPO).as_posix()) for f in group_folders(reg, "adam")} == existing
    assert any(line.startswith("by hand: ") and "features/adam" in line for line in lines)  # the interface repository
    assert all((REPO / rel).exists() for rel in existing)  # nothing was deleted


# Files outside the group that may name it, each a line or a table to drop with the group: the import-linter
# contracts, the generated catalog and Studio config (`hiru-ai catalog`, `hiru-ai studio` rewrite them) and the working
# rules (CLAUDE.md, which has a short Adam section). No code is on this list.
MAY_NAME_IT = {"pyproject.toml", "docs/AI_CATALOG.md", "langgraph.json", "CLAUDE.md"}


def test_no_code_outside_the_group_names_it_yet():
    """Phase 0 exit: nothing outside the adam folders changes behaviour or refers to them in code. (The build branch,
    the migration and the function registration arrive in Phase 6 and join the allowed list there, on purpose.)"""
    lines = remove_group(Registry().discover(), "adam", yes=False)
    named = [line.split(": ")[1] for line in lines if line.startswith("still names")]
    assert set(named) <= MAY_NAME_IT, named
