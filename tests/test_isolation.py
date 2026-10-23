"""Import boundaries (PLAN.md §4), checked by reading the source rather than trusting it.

* `contracts` imports only pydantic and the standard library: every function bundles it.
* each service under `src/services/` imports only its own package, `contracts`, the standard
  library and its declared third-party requirements — never `api` or another service.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "src" / "libs" / "contracts"
SERVICES = ROOT / "src" / "services"
STDLIB = set(sys.stdlib_module_names)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_contracts_is_standalone():
    allowed = STDLIB | {"pydantic", "contracts", "__future__"}
    for path in CONTRACTS.rglob("*.py"):
        bad = _imports(path) - allowed
        assert not bad, f"{path.relative_to(ROOT)} imports {sorted(bad)}"


def test_services_import_only_themselves_and_contracts():
    services = [p for p in SERVICES.iterdir() if p.is_dir() and not p.name.startswith("_")]
    other_services = {p.name for p in services}
    for service in services:
        for path in service.rglob("*.py"):
            imported = _imports(path)
            forbidden = imported & ({"api"} | (other_services - {service.name}))
            assert not forbidden, f"{path.relative_to(ROOT)} imports {sorted(forbidden)}"
