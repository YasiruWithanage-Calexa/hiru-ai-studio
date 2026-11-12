"""Plan/2026-11-08e §7: deleting the `raphael` folders removes Raphael. `hiru-ai remove --group raphael` must know every
folder on the plan's list (the ones that exist today are deleted, the rest are on its list for when they are made)."""

from __future__ import annotations

from hiru_ai.cli.tools import group_folders, remove_group
from hiru_ai.core import manifest as mf
from hiru_ai.core.registry import PACKAGE_ROOT, Registry

REPO = PACKAGE_ROOT.parents[2]

# The three hiru_ai/<layer>/raphael/ folders (agents, steps, systems: the layers Raphael has parts in),
# contracts/raphael/, services/shot_planner_raphael/, tests/raphael/ and
# docs/raphael/ (and the interface's features/raphael/, which is in another repository)
THE_PLAN_REMOVES = {
    *(f"src/libs/hiru_ai/{layer}/raphael" for layer in ("agents", "steps", "systems")),
    "src/libs/contracts/raphael",
    "src/services/shot_planner_raphael",
    "tests/raphael",
    "docs/raphael",
}


def test_the_removal_list_is_the_plans_list():
    reg = Registry().discover()
    declared = {f"src/libs/hiru_ai/{layer}/raphael" for layer in mf.LAYERS.values() if (layer, "raphael") in reg.groups}
    for key, group in reg.groups.items():
        if key[1] == "raphael":
            declared.update(group.folders)
    assert declared == THE_PLAN_REMOVES


def test_remove_group_on_the_real_tree_is_a_dry_run_that_lists_the_folders_that_exist():
    reg = Registry().discover()
    lines = remove_group(reg, "raphael", yes=False)
    deletions = {line.removeprefix("would delete ") for line in lines if line.startswith("would delete ")}
    existing = {rel for rel in THE_PLAN_REMOVES if (REPO / rel).exists()}
    assert deletions == existing
    assert {str(f.relative_to(REPO).as_posix()) for f in group_folders(reg, "raphael")} == existing
    assert any(line.startswith("by hand: ") and "features/raphael" in line for line in lines)
    assert all((REPO / rel).exists() for rel in existing)  # nothing was deleted


# Files outside the group that may name it, each a line or a block to drop with the group: the import-linter contracts,
# the
# generated catalog, the working rules, the function's registration, the endpoints that start it or read its result, the
# job
# kinds, the settings and the model tier, the agent loop shape it uses (generic, left in place), the migration and the
# Database pair, and the lab (kept until the person deletes it).
# No code that plans, checks or writes is on this list.
MAY_NAME_IT = {
    "pyproject.toml",
    "docs/AI_CATALOG.md",
    "langgraph.json",
    "CLAUDE.md",
    "README.md",
    ".github/workflows/deploy-functions.yml",
    "scripts/start-functions.ps1",
    ".env.example",
    "src/api/routers/scenes.py",
    "src/api/workers/task_manager.py",
    "src/libs/contracts/jobs.py",
    "src/libs/contracts/build.py",
    "src/libs/contracts/production.py",
    "src/libs/contracts/staging.py",
    "src/libs/hiru_ai/core/settings.py",
    "src/libs/hiru_ai/core/models.yaml",
    "src/libs/hiru_ai/core/agents.py",
    "src/libs/hiru_ai/core/manifest.py",
    "supabase/migrations/20261108120000_raphael.sql",
    "Database/README.md",
    "Database/schema_v19.sql",
    "Database/schema_v22.sql",  # plan/2026-11-12: a full schema, Raphael's tables in it
    "Database/upgrade_v18_to_v19.sql",
    "supabase/tests/database/019_raphael.test.sql",
}


def test_no_code_outside_the_group_names_it_beyond_the_plans_list():
    lines = remove_group(Registry().discover(), "raphael", yes=False)
    named = [line.split(": ")[1] for line in lines if line.startswith("still names")]
    assert set(named) <= MAY_NAME_IT, sorted(set(named) - MAY_NAME_IT)
