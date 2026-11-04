"""Phase 0 (plan/2026-11-04b §5.0): a layer folder can hold a GROUP of parts (`agents/adam/`), found by the registry,
kept apart by `validate`, scaffolded and removed as a set, and switched off as a set."""
from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from hiru_ai.cli import scaffold
from hiru_ai.cli.main import main
from hiru_ai.cli.tools import group_folders, group_references, remove_group, repo_root
from hiru_ai.core import manifest as mf
from hiru_ai.core.errors import HiruAIError, ManifestError, UnknownComponent
from hiru_ai.core.registry import PACKAGE_ROOT, Registry

LAYERS = ("agents", "steps", "tools", "panels", "systems", "knowledge_bases")


@pytest.fixture(autouse=True)
def _no_leaked_modules() -> Iterator[None]:
    """A registry over a throw-away folder loads a part's modules under their real dotted names
    (`Registry.module`). Put back what was loaded before and drop what the test added, so a later test never imports a
    scaffolded stand-in for `hiru_ai.agents.adam.adam_dramaturg`."""
    before = dict(sys.modules)
    yield
    for name in [n for n in sys.modules if n.startswith("hiru_ai.") and sys.modules[n] is not before.get(n)]:
        if name in before:
            sys.modules[name] = before[name]
        else:
            del sys.modules[name]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A throw-away `hiru_ai` folder shaped like the real one: <repo>/src/libs/hiru_ai."""
    return tmp_path / "src" / "libs" / "hiru_ai"


def add_group(root: Path, group: str = "adam", layers: tuple[str, ...] = LAYERS, status: str = "active",
              extra: str = "") -> None:
    for layer in layers:
        folder = root / layer / group
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "__init__.py").write_text('"""group."""\n', encoding="utf-8")
        (folder / "group.yaml").write_text(f"id: {group}\nversion: 1\nstatus: {status}\n{extra}", encoding="utf-8")


def problems(root: Path) -> list[str]:
    return [str(p) for p in Registry(root).discover().validate()]


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not in {path}"
    path.write_text(text.replace(old, new), encoding="utf-8")


# ── discovery ───────────────────────────────────────────────────────────────────────────────


def test_a_group_folder_holds_parts_the_registry_finds_by_id(root: Path):
    add_group(root)
    scaffold.create("agent", "adam_dramaturg", root, group="adam")
    scaffold.create("step", "adam_fidelity", root, group="adam")
    reg = Registry(root).discover()
    comp = reg.get("agent", "adam_dramaturg")
    assert comp.group == "adam"
    assert comp.package == "hiru_ai.agents.adam.adam_dramaturg"
    assert comp.folder == root / "agents" / "adam" / "adam_dramaturg"
    assert reg.groups[("agents", "adam")].status == "active"
    assert reg.errors == []
    assert problems(root) == []


def test_a_scaffolded_group_part_imports_by_the_grouped_path(root: Path):
    add_group(root)
    scaffold.create("agent", "adam_dramaturg", root, group="adam")
    test_file = root / "agents" / "adam" / "adam_dramaturg" / "tests" / "test_agent_adam_dramaturg.py"
    assert "from hiru_ai.agents.adam.adam_dramaturg import agent" in test_file.read_text(encoding="utf-8")


def test_the_real_registry_lists_the_same_parts_as_a_plain_read_of_every_layer():
    """Phase 0 exit: with the `adam` folders in place, every part that is not in a group is exactly what a plain
    `<layer>/*/component.yaml` read finds, and the group folders add no error."""
    reg = Registry().discover()
    plain = {(kind, p.parent.name) for kind, layer in mf.LAYERS.items()
             for p in (PACKAGE_ROOT / layer).glob("*/component.yaml")}
    assert {key for key, c in reg.components.items() if not c.group} == plain
    assert reg.groups.keys() >= {(layer, "adam") for layer in mf.LAYERS.values()}
    assert reg.errors == []


def test_a_folder_with_neither_file_is_an_error_not_a_hidden_part(root: Path):
    add_group(root)
    (root / "agents" / "typo").mkdir()
    (root / "agents" / "adam" / "adam_typo").mkdir()
    (root / "agents" / "__pycache__").mkdir()  # not a part
    texts = problems(root)
    assert any("neither component.yaml" in t and "typo" in t for t in texts)
    assert any("no component.yaml" in t and "adam_typo" in t for t in texts)
    assert not any("__pycache__" in t for t in texts)


def test_a_folder_that_is_a_part_and_a_group_is_refused(root: Path):
    add_group(root, layers=("agents",))
    (root / "agents" / "adam" / "component.yaml").write_text("id: adam\nkind: agent\n", encoding="utf-8")
    assert any("both component.yaml and group.yaml" in t for t in problems(root))


def test_a_group_id_must_equal_its_folder_and_groups_do_not_nest(root: Path):
    add_group(root, layers=("agents",))
    (root / "agents" / "adam" / "group.yaml").write_text("id: bob\n", encoding="utf-8")
    assert any("must equal the folder name" in t for t in problems(root))
    (root / "agents" / "adam" / "group.yaml").write_text("id: adam\n", encoding="utf-8")
    inner = root / "agents" / "adam" / "deeper"
    inner.mkdir()
    (inner / "group.yaml").write_text("id: deeper\n", encoding="utf-8")
    assert any("not another group" in t for t in problems(root))


def test_the_same_id_inside_and_outside_a_group_is_refused(root: Path):
    add_group(root)
    scaffold.create("agent", "adam_a", root, group="adam")
    outside = root / "agents" / "adam_a"
    outside.mkdir()
    (outside / "component.yaml").write_text(
        "id: adam_a\nkind: agent\nsummary: second one\nmodel: medium\ninput: schema:Input\noutput: schema:Output\n",
        encoding="utf-8")
    assert any("already defined" in t for t in problems(root))


def test_a_malformed_group_yaml_is_named(root: Path):
    add_group(root, layers=("agents",))
    path = root / "agents" / "adam" / "group.yaml"
    path.write_text("id: adam\ncolour: red\n", encoding="utf-8")
    assert any("group.yaml" in t and "Extra inputs" in t for t in problems(root))
    with pytest.raises(ManifestError):
        mf.load_group(path)


# ── the id rule and the naming rule ─────────────────────────────────────────────────────────


def test_scaffold_puts_a_group_part_in_the_group_and_refuses_an_adam_id_anywhere_else(root: Path):
    add_group(root)
    with pytest.raises(HiruAIError, match=r"belong to the adam group.*--group adam"):
        scaffold.create("agent", "adam_example", root)  # Phase 0 exit: outside agents/adam/
    assert not (root / "agents" / "adam_example").exists()
    with pytest.raises(HiruAIError, match="starts with 'adam_'"):
        scaffold.create("agent", "example", root, group="adam")
    with pytest.raises(HiruAIError, match="no group 'ghost'"):
        scaffold.create("agent", "ghost_example", root, group="ghost")
    scaffold.create("agent", "example", root)  # an ordinary part is untouched by the rule
    assert problems(root) == []


def test_validate_refuses_an_adam_id_outside_the_group_and_a_foreign_id_inside_it(root: Path):
    add_group(root)
    scaffold.create("agent", "example", root)
    (root / "agents" / "example").rename(root / "agents" / "adam" / "example")
    assert any("must start with 'adam_'" in t for t in problems(root))

    other = root.parent / "elsewhere"
    add_group(other)
    scaffold.create("agent", "adam_x", other, group="adam")
    (other / "agents" / "adam" / "adam_x").rename(other / "agents" / "adam_x")
    assert any("starts with 'adam_'" in t and "only parts of the adam group" in t for t in problems(other))


def test_a_group_part_names_only_its_own_group_and_nothing_outside_names_into_it(root: Path):
    add_group(root)
    scaffold.create("step", "plain_step", root)
    scaffold.create("step", "adam_step", root, group="adam")
    assert problems(root) == []

    step = root / "steps" / "adam" / "adam_step" / "component.yaml"
    edit(step, "uses: []", "uses: [plain_step]")  # a step of the group uses an ordinary step
    assert any("adam_step" in t and "outside the adam group" in t for t in problems(root))
    edit(step, "uses: [plain_step]", "uses: []")

    plain = root / "steps" / "plain_step" / "component.yaml"
    edit(plain, "uses: []", "uses: [adam_step]")  # an ordinary step uses a step of the group
    assert any("plain_step" in t and "belongs to the adam group" in t for t in problems(root))
    edit(plain, "uses: [adam_step]", "uses: []")
    assert problems(root) == []


def test_a_group_may_use_its_own_parts(root: Path):
    add_group(root)
    scaffold.create("step", "adam_a", root, group="adam")
    scaffold.create("step", "adam_b", root, group="adam")
    edit(root / "steps" / "adam" / "adam_b" / "component.yaml", "uses: []", "uses: [adam_a]")
    assert problems(root) == []


def test_a_tool_that_wraps_a_group_step_is_in_the_group(root: Path):
    add_group(root)
    scaffold.create("step", "adam_check", root, group="adam")
    scaffold.create("tool", "plain_looks", root)
    with pytest.raises(HiruAIError, match="not a step"):
        scaffold.create("tool", "plain_other", root, wraps="adam_check")  # the step is in the group, the tool is not
    scaffold.create("tool", "adam_looks", root, wraps="adam_check", group="adam")
    assert (root / "tools" / "adam" / "adam_looks" / "component.yaml").is_file()
    assert problems(root) == []


# ── the switch ──────────────────────────────────────────────────────────────────────────────


def test_a_disabled_group_switches_off_every_part_in_it(root: Path):
    add_group(root, status="disabled")
    scaffold.create("agent", "adam_a", root, group="adam")
    reg = Registry(root).discover()
    assert reg.ids("agent") == []
    assert reg.ids("agent", include_disabled=True) == ["adam_a"]
    with pytest.raises(UnknownComponent):
        reg.get("agent", "adam_a")


# ── the CLI ─────────────────────────────────────────────────────────────────────────────────


def test_the_cli_lists_and_scaffolds_by_group(root: Path, capsys: pytest.CaptureFixture[str]):
    add_group(root)
    assert main(["--root", str(root), "new", "agent", "adam_a", "--group", "adam"]) == 0
    assert main(["--root", str(root), "new", "agent", "plain"]) == 0
    capsys.readouterr()
    assert main(["--root", str(root), "list", "--group", "adam"]) == 0
    out = capsys.readouterr().out
    assert "adam_a" in out and "plain" not in out
    assert main(["--root", str(root), "list", "--group", "nope"]) == 2
    capsys.readouterr()
    assert main(["--root", str(root), "new", "agent", "adam_c"]) == 2  # refused outside the group
    assert "--group adam" in capsys.readouterr().err


def test_remove_group_lists_then_deletes_the_folders_and_names_what_still_refers_to_it(
        root: Path, capsys: pytest.CaptureFixture[str]):
    add_group(root, extra="folders:\n  - tests/adam\n  - docs/adam\noutside:\n  - the build branch\n")
    scaffold.create("agent", "adam_a", root, group="adam")
    repo = root.parents[2]
    (repo / "tests" / "adam").mkdir(parents=True)
    (repo / "tests" / "adam" / "test_x.py").write_text("from hiru_ai.agents.adam import x\n", encoding="utf-8")
    (repo / "src" / "app.py").write_text("from hiru_ai.systems.adam.shot_planner_adam import graph\n",
                                         encoding="utf-8")
    (repo / "src" / "clean.py").write_text("import os\n", encoding="utf-8")
    reg = Registry(root).discover()
    assert repo_root(reg) == repo

    dry = remove_group(reg, "adam", yes=False)
    assert "would delete tests/adam" in dry and "would delete src/libs/hiru_ai/agents/adam" in dry
    assert "would delete docs/adam" not in dry  # not there: skipped
    assert "by hand: the build branch" in dry
    still = [line for line in dry if line.startswith("still names")]
    assert len(still) == 1 and "src/app.py" in still[0]  # the group's own folders and clean files are not listed
    assert (root / "agents" / "adam").exists()  # a dry run changes nothing

    assert main(["--root", str(root), "remove", "--group", "adam", "--yes"]) == 0
    assert not (root / "agents" / "adam").exists() and not (repo / "tests" / "adam").exists()
    assert (repo / "src" / "app.py").exists()  # references are listed, never edited
    capsys.readouterr()
    with pytest.raises(HiruAIError, match="no group 'adam'"):
        group_folders(Registry(root).discover(), "adam")


def test_remove_wants_a_part_or_a_group(root: Path):
    add_group(root)
    assert main(["--root", str(root), "remove"]) == 2
    assert main(["--root", str(root), "remove", "agent", "x", "--group", "adam"]) == 2


def test_group_references_ignore_the_plans(root: Path):
    add_group(root)
    scaffold.create("agent", "adam_a", root, group="adam")
    (root.parents[2] / "plan").mkdir()
    (root.parents[2] / "plan" / "PLAN.md").write_text("adam_a everywhere\n", encoding="utf-8")
    assert group_references(Registry(root).discover(), "adam") == []
