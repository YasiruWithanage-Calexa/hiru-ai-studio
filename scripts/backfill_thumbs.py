"""Make the small copies for pictures stored before thumbnails existed (plan/2026-11-08c 1c, once).

    python scripts/backfill_thumbs.py            # count what is missing; downloads nothing
    python scripts/backfill_thumbs.py --apply    # download each missing one ONCE, write <path>.thumb.webp beside it
    python scripts/backfill_thumbs.py --apply --posters   # also take stills (<take>.poster.webp) via assemble

A picture that already has its small copy is skipped, so a second run costs only the existence checks. About 0.18 GB
is downloaded in total on the hosted project. Reads SUPABASE__URL / SUPABASE__SERVICE_ROLE_KEY (and ASSEMBLE__* for
posters) from the environment / .env.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common

_common.load_env()

import httpx  # noqa: E402

from hiru_ai.core import thumbs  # noqa: E402


def _asset_paths(assets: object) -> list[str]:
    out = []
    for a in assets if isinstance(assets, list) else []:
        path = a.get("path") if isinstance(a, dict) else a
        if path:
            out.append(str(path))
    return out


def wanted(rest: _common.Rest) -> list[tuple[str, str]]:
    """(bucket, path) of every picture a tile can show."""
    found: dict[tuple[str, str], None] = {}
    for row in rest.get("first_frames", select="storage_path", storage_path="not.is.null"):
        found[("frames", row["storage_path"])] = None
    for row in rest.get("canon_versions", select="reference_assets"):
        for p in _asset_paths(row.get("reference_assets")):
            found[("references", p)] = None
    for row in rest.get("canon_looks", select="sheet_assets"):
        for p in _asset_paths(row.get("sheet_assets")):
            found[("references", p)] = None
    return [k for k in found if not thumbs.is_thumb(k[1])]


def exists(rest: _common.Rest, bucket: str, path: str) -> bool:
    r = rest.c.head(f"{rest.storage}/object/{bucket}/{path}", headers=rest.h)
    return r.status_code == 200


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="make the missing copies (default: only count them)")
    parser.add_argument("--posters", action="store_true", help="also make take stills through the assemble service")
    args = parser.parse_args()
    rest = _common.Rest()

    missing = [(b, p) for b, p in wanted(rest) if not exists(rest, b, thumbs.thumb_path(p))]
    print(f"{len(missing)} picture(s) have no small copy.")
    made = failed = 0
    if args.apply:
        for bucket, path in missing:
            try:
                r = rest.c.get(f"{rest.storage}/object/{bucket}/{path}", headers=rest.h)
                r.raise_for_status()
                small = thumbs.make(r.content)
                if small is None:
                    raise ValueError("not a picture Pillow can read")
                # a thumbnail path is a NEW path: writing it never overwrites anything
                up = rest.c.post(f"{rest.storage}/object/{bucket}/{thumbs.thumb_path(path)}", content=small,
                                 headers={**rest.h, "Content-Type": thumbs.MIME, "x-upsert": "false"})
                up.raise_for_status()
                made += 1
            except (httpx.HTTPError, ValueError) as exc:
                failed += 1
                print(f"  skipped {bucket}/{path}: {exc}")
        print(f"made {made}, failed {failed}.")

    if args.posters:
        _posters(rest, args.apply)


def _posters(rest: _common.Rest, apply: bool) -> None:
    base = os.environ.get("ASSEMBLE__URL", "").rstrip("/")
    secret = os.environ.get("ASSEMBLE__SECRET", "")
    if not base:
        sys.exit("ASSEMBLE__URL is not set: posters are made by the assemble service.")
    todo = []
    for row in rest.get("takes", select="storage_path"):
        path = str(row["storage_path"])
        poster = path.rpartition(".")[0] + ".poster.webp"
        if not exists(rest, "takes", poster):
            todo.append((path, poster))
    print(f"{len(todo)} take(s) have no still.")
    if not apply:
        return
    made = 0
    for path, poster in todo:
        r = rest.c.post(f"{base}/poster", json={"bucket": "takes", "path": path, "out_path": poster},
                        headers={"X-Assemble-Secret": secret}, timeout=180.0)
        if r.status_code == 200 and not r.json().get("error"):
            made += 1
        else:
            print(f"  skipped {path}: {r.text[:120]}")
    print(f"made {made} still(s).")


if __name__ == "__main__":
    main()
