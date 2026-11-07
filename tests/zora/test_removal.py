"""Plan/2026-11-06e §4.0: deleting the `zora` folders removes Zora. `hiru-ai remove --group zora` must know every folder
on the plan's list (the ones that exist today are deleted, the rest are on its list for when they are made), and no
code outside the group names it beyond the plan's list."""
from __future__ import annotations

from hiru_ai.cli.tools import group_folders, remove_group
from hiru_ai.core import manifest as mf
from hiru_ai.core.registry import PACKAGE_ROOT, Registry

REPO = PACKAGE_ROOT.parents[2]

THE_PLAN_REMOVES = {
    *(f"src/libs/hiru_ai/{layer}/zora" for layer in ("agents", "steps", "systems")),
    "src/libs/contracts/zora",
    "src/services/zora_chat",
    "tests/zora",
    "tests/eval/zora",
    "lab/zora",
    "docs/zora",
}
# Files outside the group that may name it: the import-linter contract, the generated catalog, the working rules and
# the planner's own removal list (which names the two Zora files that reach its checks by id).
MAY_NAME_IT = {"pyproject.toml", "docs/AI_CATALOG.md", "CLAUDE.md", "tests/jonathan/test_removal.py",
               # Phases 4 to 7: the tier and the settings, the function's registration, the API and the database pair
               "src/libs/hiru_ai/core/models.yaml", "src/libs/hiru_ai/core/settings.py", "langgraph.json",
               ".env.example",
               ".github/workflows/deploy-functions.yml", "scripts/start-functions.ps1", "src/api/routers/zora.py",
               "src/api/services/zora.py", "src/api/repositories/__init__.py", "src/api/main.py",
               "src/api/workers/task_manager.py", "src/api/config.py", "src/libs/contracts/director.py",
               "Database/schema_v14.sql", "Database/upgrade_v13_to_v14.sql", "Database/README.md",
               "Database/schema_v15.sql", "Database/schema_v16.sql",  # whole schemas after v14
               "Database/schema_v17.sql",  # + a scene's cost
               "supabase/migrations/20261106185010_zora_revisions.sql",
               "supabase/tests/database/016_scene_plan_revisions.test.sql"}


def test_the_removal_list_is_the_plans_list():
    reg = Registry().discover()
    declared = {f"src/libs/hiru_ai/{layer}/zora" for layer in mf.LAYERS.values() if (layer, "zora") in reg.groups}
    for key, group in reg.groups.items():
        if key[1] == "zora":
            declared.update(group.folders)
    assert declared == THE_PLAN_REMOVES


def test_remove_group_on_the_real_tree_is_a_dry_run_that_lists_the_folders_that_exist():
    reg = Registry().discover()
    lines = remove_group(reg, "zora", yes=False)
    deletions = {line.removeprefix("would delete ") for line in lines if line.startswith("would delete ")}
    existing = {rel for rel in THE_PLAN_REMOVES if (REPO / rel).exists()}
    assert deletions == existing
    assert {str(f.relative_to(REPO).as_posix()) for f in group_folders(reg, "zora")} == existing
    assert any(line.startswith("by hand: ") and "features/zora" in line for line in lines)
    assert all((REPO / rel).exists() for rel in existing)  # nothing was deleted


def test_no_code_outside_the_group_names_it_beyond_the_plans_list():
    lines = remove_group(Registry().discover(), "zora", yes=False)
    named = [line.split(": ")[1] for line in lines if line.startswith("still names")]
    assert set(named) <= MAY_NAME_IT, sorted(set(named) - MAY_NAME_IT)
