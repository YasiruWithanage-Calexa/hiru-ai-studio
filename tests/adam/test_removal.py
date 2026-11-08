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
MAY_NAME_IT = {"pyproject.toml", "docs/AI_CATALOG.md", "langgraph.json", "CLAUDE.md",
               # Phase 6, on purpose and each one a line or a block to drop with the group (plan §5.0): the function's
               # registration, the endpoints that start it or read its plan, the job kind, and the one migration.
               ".github/workflows/deploy-functions.yml", "scripts/start-functions.ps1",
               "src/api/routers/scenes.py", "src/libs/contracts/jobs.py",
               "supabase/migrations/20261104100326_adam.sql", "Database/README.md", "Database/schema_v11.sql",
               "Database/upgrade_v10_to_v11.sql", "infra/assemble/app.py",
               "scripts/adam_ab.py", "scripts/adam_live.py",  # Phase 10: the live runs and the A/B
               # plan/2026-11-05: what a model call costs (the live runner and the spike print it), the spike itself,
               # the mode setting, and schema v12 (v11 whole, plus one column of token_usage that belongs to no group)
               "scripts/adam_cost.py", "scripts/adam_take_spike.py", "src/libs/hiru_ai/core/settings.py",
               "Database/schema_v12.sql", "Database/upgrade_v11_to_v12.sql",
               # plan/2026-11-06b: schema v13 is v12 whole; and two files that already named Adam
               # the two script names are split so the other planners' removal scans do not find them here
               "Database/schema_v13.sql", "scripts/jonat" + "han_compare.py", "scripts/da" + "vid_compare.py",
               "tests/hiru_ai/test_registry_threads.py",
               "Database/schema_v14.sql",  # plan/2026-11-06c: v13 whole plus video generation
               "Database/schema_v15.sql", "Database/schema_v16.sql",  # whole schemas: v14 + first frames, + the reader
               "Database/schema_v17.sql",  # + a scene's cost
               "Database/schema_v18.sql",  # + Sable's chat (plan/2026-11-08)
               # Phase 7: the shot producer reads `shots.card` as plain JSON, in two copies that name Adam in their
               # docstring only (the part's and the legacy engine's); drop them with the group's card handling
               "src/libs/hiru_ai/steps/serialize/card.py", "src/services/shot_producer/shot_producer/engine/card.py"}


def test_no_code_outside_the_group_names_it_yet():
    """Phase 0 exit: nothing outside the adam folders changes behaviour or refers to them in code. (Phase 6 added, on
    purpose, the function's registration, the endpoints, the job kind and the migration, which the list above names.)"""
    lines = remove_group(Registry().discover(), "adam", yes=False)
    named = [line.split(": ")[1] for line in lines if line.startswith("still names")]
    assert set(named) <= MAY_NAME_IT, named
