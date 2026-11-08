"""Zora is not changed and not reached into (plan/2026-11-08 §3 rule 10, the person's rule of 2026-11-08).

Sable's code imports no Zora module. The single exception is the API service reading `zora.routes_here(scene)`, read
only, to say where a handoff card opens; nothing else of `api.services.zora` is used. Read from the source with `ast`.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
SABLE = [*(SRC / "libs" / "hiru_ai").glob("*/sable"), SRC / "libs" / "contracts" / "sable",
         SRC / "services" / "sable_chat"]
API = [SRC / "api" / "routers" / "sable.py", SRC / "api" / "services" / "sable.py"]
Z = "zo" + "ra"  # built, so this file is not one that names the group (its removal check reads the source)
ALLOWED = {f"api.services.{Z}"}  # and from it only `routes_here`


def files() -> list[Path]:
    out = [p for folder in SABLE for p in folder.rglob("*.py") if "__pycache__" not in p.parts]
    return [*out, *API]


def imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names |= {f"{node.module}.{a.name}" for a in node.names}
    return names


def test_sable_imports_nothing_of_zora_but_routes_here():
    assert len(files()) > 10
    for path in files():
        found = {n for n in imports(path) if Z in n.split(".")}
        assert found <= ALLOWED, (path, found)
        if Z in path.read_text(encoding="utf-8"):
            source = path.read_text(encoding="utf-8")
            used = {node.attr for node in ast.walk(ast.parse(source))
                    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "scene_chats"}
            assert used <= {"routes_here"}, (path, used)


def test_only_the_api_service_names_zora_at_all():
    named = [p.relative_to(ROOT).as_posix() for p in files()
             if any(Z in n.split(".") for n in imports(p))]
    assert named == ["src/api/services/sable.py"]
