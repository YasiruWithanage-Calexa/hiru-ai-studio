"""What changed upstream in PromptMotion since a fork was pinned (PLAN.md §2.1, Q7).

Each forked service keeps `UPSTREAM.md`: the upstream folder (`Forked from PromptMotion
`src/services/<name>/``), the pinned commit (`commit **<sha>**`) and a table mapping each Hiru file
to the upstream file it came from. This lists, per upstream file, the commits since the pin and
the size of the change, so fixes can be pulled across by hand. It reads git only; it changes
nothing in either repository.

    python scripts/upstream_diff.py director_chat --upstream "<path to PromptMotion checkout>"
    python scripts/upstream_diff.py --patch               # every fork, with the diffs
    set PROMPTMOTION_REPO=...                             # instead of --upstream

Exit code 1 when something changed upstream (useful in a scheduled check), 2 on a setup error.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "src" / "services"
_SOURCE = re.compile(r"Forked from PromptMotion `([^`]+)`")
_COMMIT = re.compile(r"commit \*\*([0-9a-f]{7,40})\*\*")
_TICKED = re.compile(r"`([^`]+)`")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


@dataclass(frozen=True)
class Fork:
    service: str
    source: str  # upstream folder, e.g. src/services/nova_chat/
    commit: str
    files: tuple[tuple[str, str], ...]  # (hiru file, upstream path relative to `source`)


def read_fork(service_dir: Path) -> Fork:
    text = (service_dir / "UPSTREAM.md").read_text(encoding="utf-8")
    source, commit = _SOURCE.search(text), _COMMIT.search(text)
    if not source or not commit:
        raise ValueError(f"{service_dir.name}/UPSTREAM.md needs 'Forked from PromptMotion `<path>`' "
                         "and 'commit **<sha>**'")
    files: list[tuple[str, str]] = []
    for line in text.splitlines():  # | `hiru file` | `upstream file`, `another` (note) | ... |
        cells = line.split("|")[1:-1]
        if len(cells) >= 2 and (ours := _TICKED.findall(cells[0])):
            files += [(ours[0], theirs) for theirs in _TICKED.findall(cells[1]) if theirs.endswith(".py")]
    return Fork(service_dir.name, source.group(1).rstrip("/") + "/", commit.group(1), tuple(files))


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",  # noqa: S603, S607
                         check=False)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"git {' '.join(args)} failed")
    return out.stdout


def report(fork: Fork, repo: Path, ref: str, patch: bool) -> bool:
    """Print what changed; True when anything did."""
    print(f"\n== {fork.service}  (upstream {fork.source} @ {fork.commit}, compared with {ref})")
    changed = False
    for hiru_file, upstream in fork.files:
        path = fork.source + upstream
        exists = git(repo, "ls-tree", "--name-only", ref, "--", path).strip()
        if not exists:
            print(f"  {hiru_file:<28} ← {path}: GONE upstream (moved or deleted)")
            changed = True
            continue
        log = git(repo, "log", "--oneline", f"{fork.commit}..{ref}", "--", path).strip()
        if not log:
            print(f"  {hiru_file:<28} ← {path}: unchanged")
            continue
        changed = True
        stat = git(repo, "diff", "--shortstat", fork.commit, ref, "--", path).strip()
        print(f"  {hiru_file:<28} ← {path}: {stat}")
        for line in log.splitlines():
            print(f"      {line}")
        if patch:
            print(git(repo, "diff", fork.commit, ref, "--", path))
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("services", nargs="*", help="forked services (default: every one with UPSTREAM.md)")
    parser.add_argument("--upstream", default=os.environ.get("PROMPTMOTION_REPO", ""),
                        help="path to a PromptMotion checkout (or PROMPTMOTION_REPO)")
    parser.add_argument("--ref", default="HEAD", help="upstream ref to compare with (default HEAD)")
    parser.add_argument("--patch", action="store_true", help="print the diffs too")
    args = parser.parse_args()
    if not args.upstream:
        print("Give the PromptMotion checkout: --upstream <path> or PROMPTMOTION_REPO.", file=sys.stderr)
        sys.exit(2)
    repo = Path(args.upstream)
    names = args.services or sorted(p.name for p in SERVICES.iterdir() if (p / "UPSTREAM.md").exists())
    try:
        forks = [read_fork(SERVICES / n) for n in names]
        if args.ref.startswith("origin/"):
            git(repo, "fetch", "--quiet")
        for f in forks:
            git(repo, "cat-file", "-e", f"{f.commit}^{{commit}}")
        changed = [report(f, repo, args.ref, args.patch) for f in forks]
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"upstream_diff: {exc}", file=sys.stderr)
        sys.exit(2)
    sys.exit(1 if any(changed) else 0)


if __name__ == "__main__":
    main()
