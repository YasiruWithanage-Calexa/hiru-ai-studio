"""Copy the stored files from Supabase Storage to the Cloud Storage bucket (plan/2026-11-27 §4, step 3).

    python scripts/copy_media.py                 # count what is missing, copy nothing
    python scripts/copy_media.py --apply         # copy it, then compare again

Run it AFTER every process that shares the database has been switched to `FILES__BACKEND=gcs` with
`FILES__READ_FALLBACK=true`, so no new file lands in Supabase while it runs. Reads `SUPABASE__URL`,
`SUPABASE__SERVICE_ROLE_KEY` and `FILES__GCS_BUCKET` (from `.env` or the environment); the Google side uses application
default credentials. Safe to repeat. It NEVER overwrites a file already in the bucket and NEVER deletes anything: a
file in both places with different sizes is reported (after the switch the bucket's is the newer one).
Turn the fallback off only when it ends with "nothing missing".
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from urllib.parse import quote

import _common
import httpx

from hiru_ai.core import media

FOLDERS = ("documents", "frames", "references", "takes")
_PAGE = 1000


@dataclass(frozen=True)
class Stored:
    path: str
    size: int
    mime: str = "application/octet-stream"


@dataclass
class Result:
    found: int = 0
    present: int = 0
    copied: int = 0
    missing: list[str] = field(default_factory=list)
    differ: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing and not self.failed


def in_supabase(client: httpx.Client, url: str, key: str, folder: str, prefix: str = "") -> Iterator[Stored]:
    """Every object of one Supabase bucket: its list call answers one level, folders without an id."""
    offset = 0
    while True:
        r = client.post(f"{url.rstrip('/')}/storage/v1/object/list/{folder}",
                        headers={"apikey": key, "Authorization": f"Bearer {key}"},
                        json={"prefix": prefix, "limit": _PAGE, "offset": offset,
                              "sortBy": {"column": "name", "order": "asc"}})
        r.raise_for_status()
        entries = r.json()
        for entry in entries:
            path = f"{prefix}{entry['name']}"
            if entry.get("id") is None:
                yield from in_supabase(client, url, key, folder, f"{path}/")
            else:
                meta = entry.get("metadata") or {}
                yield Stored(path, int(meta.get("size") or 0), str(meta.get("mimetype") or Stored.mime))
        if len(entries) < _PAGE:
            return
        offset += _PAGE


def in_bucket(client: httpx.Client, target: media.Media, folder: str) -> dict[str, int]:
    """path -> size of every object under one folder of the bucket."""
    headers = target.reads(folder, "x")[0].headers
    base = f"{media.GCS}/storage/v1/b/{target.config.bucket}/o?prefix={quote(folder + '/', safe='')}" \
           "&fields=items(name,size),nextPageToken&maxResults=1000"
    out: dict[str, int] = {}
    page = ""
    while True:
        r = client.get(base + (f"&pageToken={quote(page, safe='')}" if page else ""), headers=headers)
        r.raise_for_status()
        body = r.json()
        for item in body.get("items") or []:
            out[str(item["name"]).removeprefix(f"{folder}/")] = int(item.get("size") or 0)
        page = str(body.get("nextPageToken") or "")
        if not page:
            return out


def copy_folder(client: httpx.Client, source: media.Media, target: media.Media, url: str, key: str, folder: str,
                apply: bool) -> Result:
    result = Result()
    have = in_bucket(client, target, folder)
    for item in in_supabase(client, url, key, folder):
        if item.path.rsplit("/", 1)[-1] == ".emptyFolderPlaceholder":  # Supabase's own marker, not a file
            continue
        result.found += 1
        if item.path in have:
            result.present += 1
            if have[item.path] != item.size:
                result.differ.append(item.path)
            continue
        if not apply:
            result.missing.append(item.path)
            continue
        try:
            got = media.get(client, source, folder, item.path)
            got.raise_for_status()
            sent = media.put(client, target, folder, item.path, got.content, item.mime, once=True)
            if not media.already_exists(sent):  # written while this ran: it is there
                sent.raise_for_status()
            result.copied += 1
        except httpx.HTTPError as exc:
            result.failed.append(item.path)
            print(f"  failed {folder}/{item.path}: {type(exc).__name__}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="copy the missing files (default: only count them)")
    args = parser.parse_args(argv)
    _common.load_env()
    url, key = os.environ["SUPABASE__URL"], os.environ["SUPABASE__SERVICE_ROLE_KEY"]
    bucket = os.environ.get("FILES__GCS_BUCKET", "").strip()
    if not bucket:
        print("Set FILES__GCS_BUCKET.")
        return 2
    source = media.Media(url, key, media.MediaConfig())
    target = media.Media(url, key, media.MediaConfig(backend="gcs", bucket=bucket))
    print(f"Supabase {url} -> gs://{bucket}" + ("" if args.apply else "   (dry run: nothing is written)"))

    complete = True
    with httpx.Client(timeout=300.0) as client:
        for folder in FOLDERS:
            result = copy_folder(client, source, target, url, key, folder, args.apply)
            print(f"{folder}: {result.found} in Supabase, {result.present} already in the bucket, "
                  f"{result.copied} copied, {len(result.missing)} missing, {len(result.failed)} failed, "
                  f"{len(result.differ)} of a different size")
            for path in result.differ[:20]:
                print(f"  different size (left as it is): {folder}/{path}")
            complete = complete and result.complete
    print("Nothing missing." if complete else "Not complete: keep FILES__READ_FALLBACK=true.")
    return 0 if complete else 1


if __name__ == "__main__":
    sys.exit(main())
