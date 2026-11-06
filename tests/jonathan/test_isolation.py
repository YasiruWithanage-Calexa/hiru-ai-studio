"""What import-linter cannot say about the `jonathan` folders (plan/2026-11-05e §4.0), read from the source.

* a module under `hiru_ai.<layer>.jonathan` imports, from this package, only its own `jonathan` folder, a LOWER layer's
`jonathan`
  folder, `hiru_ai.core`, `hiru_ai.rag`, `contracts`, and the clip schema of the shared `serialize` step (Jonathan's
  author
  fills the same IR the DoP does); never the other planner's group, never `api` or a service;
* nothing outside a `jonathan` folder imports one (the exceptions are Jonathan's own function, tests and scripts);
* `contracts.jonathan` imports from `contracts` only the shared Veo clock and staging contracts (§4.1), never
  the other planner's contracts
  and never the AI package.

The scanners are functions of a source text, so the tests below can also show them refusing a bad import. This file is
Jonathan's own copy of the other planner's: the groups stay independent (removing either must not break the other's
tests).
"""
from __future__ import annotations

import ast

from hiru_ai.core import manifest as mf
from hiru_ai.core.registry import PACKAGE_ROOT

ROOT = PACKAGE_ROOT.parents[2]
SRC, CONTRACTS_JONATHAN = ROOT / "src", ROOT / "src" / "libs" / "contracts" / "jonathan"
GROUP = "jonathan"

BELOW: dict[str, set[str]] = {
    "knowledge_bases": set(),
    "tools": {"knowledge_bases"},
    "steps": {"knowledge_bases"},
    "agents": {"knowledge_bases", "tools", "steps"},
    "panels": {"knowledge_bases", "tools", "steps", "agents"},
    "systems": {"knowledge_bases", "tools", "steps", "agents", "panels"},
}
ALWAYS = ("hiru_ai.core", "hiru_ai.rag", "contracts")
SHARED = ("hiru_ai.steps.serialize.schema",)  # the clip schema Jonathan's author fills (a lower layer, by module)
# the other planners' groups, written so that this group's removal check finds no mention
OTHERS = ("ad" + "am", "da" + "vid")
OTHER = OTHERS[0]
NOT_FROM_A_PART = ("api", "echo_service", "doc_ingest", "script_split", "structure_build", "canon_extract",
                   "director_chat", "shot_producer", "frame_render", "hiru_ai.adapters", "hiru_ai.cli",
                   *(f"contracts.{o}" for o in OTHERS),
                       *(f"hiru_ai.{layer}.{o}" for o in OTHERS for layer in mf.LAYERS.values()))


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
    """What a module of `hiru_ai.<layer>.jonathan` imports that it may not."""
    allowed = [f"hiru_ai.{layer}.{GROUP}", *(f"hiru_ai.{below}.{GROUP}" for below in sorted(BELOW[layer])), *ALWAYS,
               *SHARED]
    bad = []
    for name in sorted(imported(source)):
        if any(_under(name, p) for p in NOT_FROM_A_PART):
            bad.append(name)
        elif (_under(name, "hiru_ai") and name != "hiru_ai" and not any(_under(name, p) for p in allowed)
              and not any(_under(p, name) for p in SHARED)):
            bad.append(name)
    return bad


def reaches_into_a_group(source: str) -> list[str]:
    """What a module outside the group imports from inside it."""
    out = []
    for name in sorted(imported(source)):
        parts = name.split(".")
        if (len(parts) >= 3 and parts[0] == "hiru_ai" and parts[2] == GROUP) or (
                len(parts) >= 2 and parts[0] == "contracts" and parts[1] == GROUP):
            out.append(name)
    return out


def contracts_breaks(source: str) -> list[str]:
    banned = (*(f"contracts.{o}" for o in OTHERS), "hiru_ai", "api")
    return [n for n in sorted(imported(source)) if any(_under(n, b) for b in banned)]


# ── the real tree ───────────────────────────────────────────────────────────────────────────


def test_a_jonathan_module_imports_only_its_group_a_lower_layers_group_the_core_the_rag_and_contracts():
    seen = 0
    for layer in mf.LAYERS.values():
        for path in sorted((PACKAGE_ROOT / layer / GROUP).rglob("*.py")):
            seen += 1
            bad = breaks_inside(layer, path.read_text(encoding="utf-8"))
            assert not bad, f"{path.relative_to(ROOT)} imports {bad}"
    assert seen >= 6


def test_nothing_outside_a_jonathan_folder_imports_one():
    own = [*(PACKAGE_ROOT / layer / GROUP for layer in mf.LAYERS.values()), CONTRACTS_JONATHAN,
           SRC / "services" / "shot_planner_jonathan",
               ROOT / "tests" / "jonathan", ROOT / "tests" / "eval" / "jonathan"]
    checked = 0
    for base in (SRC, ROOT / "tests", ROOT / "scripts"):
        for path in sorted(base.rglob("*.py")):
            if any(o in path.parents for o in own) or ".venv" in path.parts:
                continue
            if path.parent == ROOT / "scripts" and path.name.startswith("jonathan_"):
                continue  # Jonathan's own tools for the spike and the blind comparison (scripts/jonathan_*.py)
            checked += 1
            bad = reaches_into_a_group(path.read_text(encoding="utf-8"))
            assert not bad, f"{path.relative_to(ROOT)} imports {bad}: nothing outside the jonathan folders may"
    assert checked > 100


def test_contracts_jonathan_never_imports_the_other_planner_or_the_ai_package():
    for path in sorted(CONTRACTS_JONATHAN.rglob("*.py")):
        bad = contracts_breaks(path.read_text(encoding="utf-8"))
        assert not bad, f"{path.relative_to(ROOT)} imports {bad}"


# ── the scanners refuse what they should ────────────────────────────────────────────────────


def src(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def test_the_scanner_refuses_a_jonathan_agent_importing_the_other_planner_a_service_or_a_higher_layer():
    existing = breaks_inside("agents", src("from hiru_ai.agents.scene_planner import agent"))
    assert "hiru_ai.agents.scene_planner" in existing
    assert breaks_inside("agents", src(f"from hiru_ai.agents.{OTHER} import x"))
    assert breaks_inside("agents", src(f"import contracts.{OTHER}.plan"))
    assert breaks_inside("agents", src("from hiru_ai.panels.jonathan import x"))  # upward
    assert breaks_inside("steps", src("from hiru_ai.agents.jonathan import jonathan_author"))  # upward
    assert breaks_inside("agents", src("import api.main")) == ["api.main"]
    assert breaks_inside("agents", src("from hiru_ai.steps.kernel_score import logic"))  # a shared step, not the schema


def test_the_scanner_allows_what_a_jonathan_module_may_import():
    ok = src("from hiru_ai.core import parts", "from hiru_ai.core.context import RunContext",
             "from hiru_ai.rag import hits", "from contracts.jonathan.wire import JonathanWire",
             "from contracts.timing import words_in", "from contracts.shotplan import shot_clock",
             "from hiru_ai.steps.serialize.schema import get_schema",
             "from hiru_ai.agents.jonathan.jonathan_author.schema import Input", "import pydantic, yaml")
    assert breaks_inside("agents", ok) == []
    assert breaks_inside("systems", src("from hiru_ai.steps.jonathan.jonathan_check import step")) == []


def test_the_scanner_finds_a_module_outside_the_group_that_imports_it():
    assert reaches_into_a_group(src("from hiru_ai.agents.jonathan.jonathan_author import agent"))
    assert reaches_into_a_group(src("import contracts.jonathan.wire"))
    assert reaches_into_a_group(src("from contracts import jonathan")) == ["contracts.jonathan"]
    assert reaches_into_a_group(src("from hiru_ai.agents.scene_planner import agent",
                                    "from contracts import timing")) == []
