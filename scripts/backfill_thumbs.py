"""Make the small copies for pictures stored before thumbnails existed (plan/2026-11-08c 1c; plan/2026-11-21 phase 6).

    python scripts/backfill_thumbs.py            # DRY RUN: list what is missing and its size; downloads nothing
    python scripts/backfill_thumbs.py --apply    # write <path>.thumb.webp beside each; sources read through the
                                                 # shared file cache (plan/2026-11-21 D9): one on disk costs nothing
    python scripts/backfill_thumbs.py --apply --posters   # also take stills, recorded on the takes (schema v24)

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
from hiru_ai.core.file_store import CachedFiles  # noqa: E402


class RestFiles:
    """`_common.Rest` as the `Files` port, so the sources go through `CachedFiles` (the API's own disk copy)."""

    def __init__(self, rest: _common.Rest) -> None:
        self.rest = rest

    def download(self, bucket: str, path: str) -> bytes:
        return self.rest.download(bucket, path)

    def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None:
        # a thumbnail path is a NEW path: writing it never overwrites anything
        self.rest.upload(bucket, path, data, mime, once=True)


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
    return rest.size(bucket, path) is not None


def size(rest: _common.Rest, bucket: str, path: str) -> int:
    """The object's size from a HEAD (no body crosses the internet); 0 when unknown."""
    return rest.size(bucket, path) or 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="make the missing copies (default: only count them)")
    parser.add_argument("--posters", action="store_true", help="also make take stills through the assemble service")
    args = parser.parse_args()
    rest = _common.Rest()

    missing = [(b, p) for b, p in wanted(rest) if not exists(rest, b, thumbs.thumb_path(p))]
    total = 0
    for bucket, path in missing:
        n = size(rest, bucket, path)
        total += n
        print(f"  {bucket}/{path}  {n / 1024**2:.2f} MB")
    print(f"{len(missing)} picture(s) have no small copy ({total / 1024**2:.1f} MB of sources).")
    made = failed = 0
    if args.apply:
        files = CachedFiles(RestFiles(rest))
        for bucket, path in missing:
            try:
                small = thumbs.make(files.download(bucket, path))
                if small is None:
                    raise ValueError("not a picture Pillow can read")
                files.inner.upload(bucket, thumbs.thumb_path(path), small, thumbs.MIME)
                made += 1
            except (httpx.HTTPError, ValueError) as exc:
                failed += 1
                print(f"  skipped {bucket}/{path}: {exc}")
        print(f"made {made}, failed {failed}. {files.summary()}")
    else:
        print("Dry run: nothing downloaded or written. Run again with --apply to make them.")

    if args.posters:
        _posters(rest, args.apply)


def _posters(rest: _common.Rest, apply: bool) -> None:
    base = os.environ.get("ASSEMBLE__URL", "").rstrip("/")
    secret = os.environ.get("ASSEMBLE__SECRET", "")
    if not base:
        sys.exit("ASSEMBLE__URL is not set: posters are made by the assemble service.")
    todo = []
    for row in rest.get("takes", select="storage_path,poster_path"):
        path = str(row["storage_path"])
        poster = path.rpartition(".")[0] + ".poster.webp"
        if not row.get("poster_path") or not exists(rest, "takes", poster):
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
            # Record it (schema v24): the card shows a still only when the row says it exists.
            saved = rest.c.patch(f"{rest.rest}/takes", headers=rest.h, params={"storage_path": f"eq.{path}"},
                                 json={"poster_path": poster})
            if saved.status_code == 400 and "poster_path" in saved.text:
                sys.exit("takes.poster_path is missing: apply Database/upgrade_v23_to_v24.sql first.")
            saved.raise_for_status()
        else:
            print(f"  skipped {path}: {r.text[:120]}")
    print(f"made {made} still(s).")


if __name__ == "__main__":
    main()
