"""Plan/2026-11-05e §4.0: deleting the `david` folders removes David. `hiru-ai remove --group david` must know every
folder
on the plan's list (the ones that exist today are deleted, the rest are on its list for when they are made)."""
from __future__ import annotations

from hiru_ai.cli.tools import group_folders, remove_group
from hiru_ai.core import manifest as mf
from hiru_ai.core.registry import PACKAGE_ROOT, Registry

REPO = PACKAGE_ROOT.parents[2]

# §4.0: the six hiru_ai/<layer>/david/ folders, contracts/david/, services/shot_planner_david/, tests/david/,
# tests/eval/david/, docs/david/ (and the interface's features/david/, which is in another repository)
THE_PLAN_REMOVES = {
    *(f"src/libs/hiru_ai/{layer}/david" for layer in mf.LAYERS.values()),
    "src/libs/contracts/david",
    "src/services/shot_planner_david",
    "tests/david",
    "tests/eval/david",
    "docs/david",
}


def test_the_removal_list_is_the_plans_list():
    reg = Registry().discover()
    declared = {f"src/libs/hiru_ai/{layer}/david" for layer in mf.LAYERS.values() if (layer, "david") in reg.groups}
    for key, group in reg.groups.items():
        if key[1] == "david":
            declared.update(group.folders)
    assert declared == THE_PLAN_REMOVES


def test_remove_group_on_the_real_tree_is_a_dry_run_that_lists_the_folders_that_exist():
    reg = Registry().discover()
    lines = remove_group(reg, "david", yes=False)
    deletions = {line.removeprefix("would delete ") for line in lines if line.startswith("would delete ")}
    existing = {rel for rel in THE_PLAN_REMOVES if (REPO / rel).exists()}
    assert deletions == existing
    assert {str(f.relative_to(REPO).as_posix()) for f in group_folders(reg, "david")} == existing
    assert any(line.startswith("by hand: ") and "features/david" in line for line in lines)
    assert all((REPO / rel).exists() for rel in existing)  # nothing was deleted


# Files outside the group that may name it, each a line or a block to drop with the group: the import-linter contracts,
# the generated catalog, the working rules, the function's registration, the endpoints that start it or read its
# plan, the
# job kind, the settings, the migration and the Database pair, and the live tools (the spike and the blind comparison).
# No code that plans, checks or writes is on this list.
MAY_NAME_IT = {
    "pyproject.toml", "docs/AI_CATALOG.md", "docs/AI_PATTERN.md", "docs/adr/0010-one-author-pattern.md",
    "docs/adr/README.md", "langgraph.json", "CLAUDE.md", "README.md",
    ".github/workflows/deploy-functions.yml", "scripts/start-functions.ps1", ".env.example",
    "src/api/routers/scenes.py", "src/api/workers/task_manager.py", "src/libs/contracts/jobs.py",
    "src/libs/contracts/build.py", "src/libs/contracts/production.py", "src/libs/contracts/staging.py",
    "src/libs/hiru_ai/core/settings.py", "src/libs/hiru_ai/core/models.yaml",
    "supabase/migrations/20261105120000_david.sql", "Database/README.md", "Database/schema_v12.sql",
    "Database/schema_v13.sql",  # v12 whole plus plan/2026-11-06b
    "Database/schema_v14.sql",  # v13 whole plus plan/2026-11-06c
    "Database/upgrade_v11_to_v12.sql", "scripts/david_spike.py", "scripts/david_compare.py",
    "supabase/tests/database/013_david.test.sql",
}


def test_no_code_outside_the_group_names_it_beyond_the_plans_list():
    lines = remove_group(Registry().discover(), "david", yes=False)
    named = [line.split(": ")[1] for line in lines if line.startswith("still names")]
    assert set(named) <= MAY_NAME_IT, sorted(set(named) - MAY_NAME_IT)
