"""What import-linter cannot say about the `adam` folders (plan/2026-11-04b §5.0 rule 4), read from the source.

* a module under `hiru_ai.<layer>.adam` imports, from this package, only its own `adam` folder, a LOWER layer's `adam`
  folder, `hiru_ai.core`, `hiru_ai.rag` and `contracts` (and never `api` or a service);
* nothing outside an `adam` folder imports one (the exceptions are Adam's own function and tests);
* `contracts.adam` imports, from `contracts`, only `contracts.timing`, the Veo clock (one source of truth).

The scanners are functions of a source text, so the tests below can also show them refusing a bad import.
"""
from __future__ import annotations

import ast

from hiru_ai.core import manifest as mf
from hiru_ai.core.registry import PACKAGE_ROOT

ROOT = PACKAGE_ROOT.parents[2]
SRC, CONTRACTS_ADAM = ROOT / "src", ROOT / "src" / "libs" / "contracts" / "adam"
GROUP = "adam"

# layer folder → the layer folders below it (a part imports downward only; core and rag are always allowed)
BELOW: dict[str, set[str]] = {
    "knowledge_bases": set(),
    "tools": {"knowledge_bases"},
    "steps": {"knowledge_bases"},
    "agents": {"knowledge_bases", "tools", "steps"},
    "panels": {"knowledge_bases", "tools", "steps", "agents"},
    "systems": {"knowledge_bases", "tools", "steps", "agents", "panels"},
}
ALWAYS = ("hiru_ai.core", "hiru_ai.rag", "contracts")
NOT_FROM_A_PART = ("api", "echo_service", "doc_ingest", "script_split", "structure_build", "canon_extract",
                   "director_chat", "shot_producer", "frame_render", "hiru_ai.adapters", "hiru_ai.cli")


def imported(source: str) -> set[str]:
    """Every dotted module a source imports; `from a import b` also yields `a.b` (b may be a module)."""
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
    """What a module of `hiru_ai.<layer>.adam` imports that it may not."""
    allowed = [f"hiru_ai.{layer}.{GROUP}", *(f"hiru_ai.{below}.{GROUP}" for below in sorted(BELOW[layer])), *ALWAYS]
    bad = []
    for name in sorted(imported(source)):
        if any(_under(name, p) for p in NOT_FROM_A_PART):
            bad.append(name)
        elif _under(name, "hiru_ai") and not any(_under(name, p) for p in allowed) and name != "hiru_ai":
            bad.append(name)
    return bad


def reaches_into_a_group(source: str) -> list[str]:
    """What a module outside the group imports from inside it."""
    out = []
    for name in sorted(imported(source)):
        parts = name.split(".")
        if (len(parts) >= 3 and parts[0] == "hiru_ai" and parts[2] == GROUP) or name.startswith(f"contracts.{GROUP}") \
                or (len(parts) >= 2 and parts[0] == "contracts" and parts[1] == GROUP):
            out.append(name)
    return out


def contracts_breaks(source: str) -> list[str]:
    shared = (["timing"], [GROUP])
    return [n for n in sorted(imported(source)) if n.startswith("contracts") and n != "contracts"
            and n.split(".")[1:2] not in shared]


# ── the real tree ───────────────────────────────────────────────────────────────────────────


def test_an_adam_module_imports_only_its_group_a_lower_layers_group_the_core_the_rag_and_contracts():
    seen = 0
    for layer in mf.LAYERS.values():
        for path in sorted((PACKAGE_ROOT / layer / GROUP).rglob("*.py")):
            seen += 1
            bad = breaks_inside(layer, path.read_text(encoding="utf-8"))
            assert not bad, f"{path.relative_to(ROOT)} imports {bad}"
    assert seen >= 6  # at least the six __init__.py files


def test_nothing_outside_an_adam_folder_imports_one():
    own = [*(PACKAGE_ROOT / layer / GROUP for layer in mf.LAYERS.values()), CONTRACTS_ADAM,
           SRC / "services" / "shot_planner_adam", ROOT / "tests" / "adam", ROOT / "tests" / "eval" / "adam"]
    checked = 0
    for base in (SRC, ROOT / "tests", ROOT / "scripts"):
        for path in sorted(base.rglob("*.py")):
            if any(o in path.parents for o in own) or ".venv" in path.parts:
                continue
            checked += 1
            bad = reaches_into_a_group(path.read_text(encoding="utf-8"))
            assert not bad, f"{path.relative_to(ROOT)} imports {bad}: nothing outside the adam folders may"
    assert checked > 100


def test_contracts_adam_imports_only_the_veo_clock_from_contracts():
    for path in sorted(CONTRACTS_ADAM.rglob("*.py")) if CONTRACTS_ADAM.is_dir() else []:
        bad = contracts_breaks(path.read_text(encoding="utf-8"))
        assert not bad, f"{path.relative_to(ROOT)} imports {bad}; only contracts.timing is shared"


# ── the scanners refuse what they should ────────────────────────────────────────────────────


def src(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def test_the_scanner_refuses_an_adam_agent_importing_an_existing_agent_a_service_or_a_higher_layer():
    existing = src("from hiru_ai.agents.scene_planner import agent")
    assert "hiru_ai.agents.scene_planner" in breaks_inside("agents", existing)
    assert "hiru_ai.steps.kernel_score" in breaks_inside("agents", src("from hiru_ai.steps.kernel_score import logic"))
    assert breaks_inside("agents", src("from hiru_ai.panels.adam import adam_screening"))  # upward
    assert breaks_inside("steps", src("from hiru_ai.agents.adam import adam_dramaturg"))  # upward
    assert breaks_inside("agents", src("import api.main")) == ["api.main"]
    assert breaks_inside("agents", src("from hiru_ai.adapters import supabase_rest"))
    assert breaks_inside("agents", src("from hiru_ai.cli import main"))
    assert breaks_inside("agents", src("import script_split.engine")) == ["script_split.engine"]


def test_the_scanner_allows_what_an_adam_module_may_import():
    ok = src("from hiru_ai.core import parts", "from hiru_ai.core.context import RunContext",
             "from hiru_ai.rag import hits", "from contracts.adam.plan import ShotCard",
             "from contracts.timing import words_in", "from hiru_ai.agents.adam.adam_dramaturg.schema import Input",
             "from hiru_ai.steps.adam.adam_fit import step", "import pydantic, yaml")
    assert breaks_inside("agents", ok) == []
    assert breaks_inside("systems", src("from hiru_ai.panels.adam.adam_screening import graph")) == []


def test_the_scanner_finds_a_module_outside_the_group_that_imports_it():
    assert reaches_into_a_group(src("from hiru_ai.agents.adam.adam_dramaturg import agent"))
    assert reaches_into_a_group(src("from hiru_ai.agents import adam")) == ["hiru_ai.agents.adam"]
    assert reaches_into_a_group(src("import contracts.adam.plan"))
    assert reaches_into_a_group(src("from contracts import adam")) == ["contracts.adam"]
    assert reaches_into_a_group(src("from hiru_ai.agents.scene_planner import agent",
                                    "from contracts import timing")) == []


def test_the_scanner_finds_contracts_adam_importing_another_contract():
    assert "contracts.shotplan" in contracts_breaks(src("from contracts.shotplan import Item"))
    assert contracts_breaks(src("from contracts import shotplan")) == ["contracts.shotplan"]
    assert contracts_breaks(src("from contracts.timing import words_in", "from contracts.adam.tiers import TIERS",
                                "import contracts")) == []
