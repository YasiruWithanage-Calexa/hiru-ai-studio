"""What import-linter cannot say about the `zora` folders (plan/2026-11-06e §2 rule 2, §4.0; plan/2026-11-13 §3.11),
read from the source.

* a module under `hiru_ai.<layer>.zora` imports, from this package, only its own `zora` folder, a LOWER layer's `zora`
  folder, `hiru_ai.core`, `hiru_ai.rag` and `contracts`; never a planner's group, the old director chat, `api` or a
  service. It reaches the planner's checks BY ID (`core.parts`), so removing either group never breaks the other's
  imports;
* nothing outside a `zora` folder imports one (Zora's own lab is the exception);
* `contracts.zora` imports only the standard library, pydantic and itself;
* no Zora file imports or names a planner as a code identifier (plan/2026-11-13: "the planner plans, Zora edits").
"""
from __future__ import annotations

import ast

from hiru_ai.core import manifest as mf
from hiru_ai.core.registry import PACKAGE_ROOT

ROOT = PACKAGE_ROOT.parents[2]
SRC, CONTRACTS_ZORA = ROOT / "src", ROOT / "src" / "libs" / "contracts" / "zora"
GROUP = "zora"
BELOW: dict[str, set[str]] = {
    "knowledge_bases": set(),
    "tools": {"knowledge_bases"},
    "steps": {"knowledge_bases"},
    "agents": {"knowledge_bases", "tools", "steps"},
    "panels": {"knowledge_bases", "tools", "steps", "agents"},
    "systems": {"knowledge_bases", "tools", "steps", "agents", "panels"},
}
ALWAYS = ("hiru_ai.core", "hiru_ai.rag", "contracts")
# the planners' groups, written so that their removal checks find no mention here
PLANNERS = ("ad" + "am", "da" + "vid", "jona" + "than", "raph" + "ael", "clas" + "sic")
OLD_CHAT = ("director_chat", "scene_kernel")  # the old chat: Zora copies its guards, never imports them
NOT_FROM_A_PART = ("api", "hiru_ai.adapters", "hiru_ai.cli", *(f"contracts.{p}" for p in PLANNERS),
                   *(f"hiru_ai.{layer}.{p}" for p in PLANNERS for layer in mf.LAYERS.values()))
STDLIB = {"__future__", "re", "json", "typing", "dataclasses", "collections", "functools", "uuid"}


def imported(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


def _under(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def breaks_inside(layer: str, source: str) -> list[str]:
    allowed = [f"hiru_ai.{layer}.{GROUP}", *(f"hiru_ai.{below}.{GROUP}" for below in sorted(BELOW[layer])), *ALWAYS]
    bad = []
    for name in sorted(imported(source)):
        if any(_under(name, p) for p in NOT_FROM_A_PART) or any(part in OLD_CHAT for part in name.split(".")):
            bad.append(name)
        elif _under(name, "hiru_ai") and name != "hiru_ai" and not any(_under(name, p) for p in allowed):
            bad.append(name)
    return bad


def reaches_into_the_group(source: str) -> list[str]:
    out = []
    for name in sorted(imported(source)):
        parts = name.split(".")
        if (len(parts) >= 3 and parts[0] == "hiru_ai" and parts[2] == GROUP) or (
                len(parts) >= 2 and parts[0] == "contracts" and parts[1] == GROUP):
            out.append(name)
    return out


def contracts_breaks(source: str) -> list[str]:
    return [n for n in sorted(imported(source))
            if not (_under(n, "contracts.zora") or _under(n, "pydantic") or n.split(".")[0] in STDLIB)]


# ── the real tree ───────────────────────────────────────────────────────────────────────────


def test_a_zora_module_imports_only_its_group_a_lower_layers_group_the_core_the_rag_and_contracts():
    seen = 0
    for layer in mf.LAYERS.values():
        for path in sorted((PACKAGE_ROOT / layer / GROUP).rglob("*.py")):
            seen += 1
            bad = breaks_inside(layer, path.read_text(encoding="utf-8"))
            assert not bad, f"{path.relative_to(ROOT)} imports {bad}"
    assert seen >= 10


def test_nothing_outside_a_zora_folder_imports_one():
    own = [*(PACKAGE_ROOT / layer / GROUP for layer in mf.LAYERS.values()), CONTRACTS_ZORA,
           SRC / "services" / "zora_chat", ROOT / "tests" / "zora", ROOT / "tests" / "eval" / "zora"]
    checked = 0
    for base in (SRC, ROOT / "tests", ROOT / "scripts"):
        for path in sorted(base.rglob("*.py")):
            if any(o in path.parents for o in own) or ".venv" in path.parts:
                continue
            checked += 1
            bad = reaches_into_the_group(path.read_text(encoding="utf-8"))
            assert not bad, f"{path.relative_to(ROOT)} imports {bad}: nothing outside the zora folders may"
    assert checked > 100


def test_contracts_zora_imports_only_the_standard_library_pydantic_and_itself():
    for path in sorted(CONTRACTS_ZORA.rglob("*.py")):
        bad = contracts_breaks(path.read_text(encoding="utf-8"))
        assert not bad, f"{path.relative_to(ROOT)} imports {bad}"


# ── the scanners refuse what they should ────────────────────────────────────────────────────


def src(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def test_the_scanner_refuses_a_planner_the_old_chat_and_a_higher_layer():
    assert breaks_inside("steps", src(f"from hiru_ai.steps.{PLANNERS[2]}.x_check import step"))
    assert breaks_inside("steps", src(f"import contracts.{PLANNERS[2]}.wire"))
    assert breaks_inside("steps", src("from hiru_ai.steps.scene_kernel import logic"))
    assert breaks_inside("systems", src("from hiru_ai.systems.director_chat import graph"))
    assert breaks_inside("steps", src("from hiru_ai.agents.zora import x"))  # upward
    assert breaks_inside("steps", src("import api.main")) == ["api.main"]


def test_the_scanner_allows_what_a_zora_module_may_import():
    assert breaks_inside("steps", src("from hiru_ai.core import parts", "from contracts.zora.wire import to_op")) == []
    assert breaks_inside("systems", src("from contracts.coverage.scene import Coverage")) == []
    assert contracts_breaks(src("from hiru_ai.core import parts")) == ["hiru_ai.core", "hiru_ai.core.parts"]
    assert contracts_breaks(src("from pydantic import BaseModel", "from typing import Any")) == []


# ── no planner (plan/2026-11-13 §3.11) ──────────────────────────────────────────────────────────


def identifiers(source: str) -> set[str]:
    """Every name the code uses: variables, attributes, functions, classes, arguments, imported modules."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.arg):
            out.add(node.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            out.update(a.name for a in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                out.update(node.module.split("."))
    return out


def names_a_planner(source: str) -> list[str]:
    return sorted(n for n in identifiers(source) for p in PLANNERS if p in n.lower())


def test_no_zora_file_imports_or_names_a_planner():
    folders = [*(PACKAGE_ROOT / layer / GROUP for layer in mf.LAYERS.values()), CONTRACTS_ZORA,
               SRC / "services" / "zora_chat", SRC / "api" / "routers" / "zora.py",
               SRC / "api" / "services" / "zora.py"]
    seen = 0
    for base in folders:
        for path in ([base] if base.is_file() else sorted(base.rglob("*.py"))):
            seen += 1
            text = path.read_text(encoding="utf-8")
            bad = names_a_planner(text)
            assert not bad, f"{path.relative_to(ROOT)} names {bad}"
            assert not [n for n in imported(text) if any(p in n for p in PLANNERS)], path
    assert seen >= 10


def test_the_planner_scanner_refuses_a_name():
    assert names_a_planner(src(f"PLANNER = '{PLANNERS[2]}'")) == []  # a string is not a name
    assert names_a_planner(src(f"def {PLANNERS[3]}_check(): pass")) == [f"{PLANNERS[3]}_check"]
