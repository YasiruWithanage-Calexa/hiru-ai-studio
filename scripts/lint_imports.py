"""Run import-linter with every service folder on the path (plan/2026-11-03 Phase 0).

A Cloud Run function runs from its own folder, so each service package sits at a different
path root. import-linter resolves `root_packages` from `sys.path`; this puts them there, then
hands over to its CLI. Arguments are passed through (`--verbose`, `--contract <id>`).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    from importlinter.cli import lint_imports_command

    for stream in (sys.stdout, sys.stderr):  # rich draws emoji; a redirected Windows console is cp1252
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    services = sorted(p for p in (ROOT / "src" / "services").iterdir() if p.is_dir() and not p.name.startswith("_"))
    for path in [ROOT / "src", ROOT / "src" / "libs", *services]:
        sys.path.insert(0, str(path))
    code = lint_imports_command.main(
        args=["--config", str(ROOT / "pyproject.toml"), *sys.argv[1:]], standalone_mode=False
    )
    return int(code or 0)


if __name__ == "__main__":
    sys.exit(main())
