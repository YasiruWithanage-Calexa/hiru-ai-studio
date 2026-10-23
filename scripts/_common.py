"""Shared setup for the admin/eval scripts: paths, .env, a small service-role REST client.

Scripts are operator tools, not deployed code, so they may import the doc_ingest engine
directly (one chunker, one embedding path) — the isolation rule applies to services, not here.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT / "src" / "libs", ROOT / "src" / "services" / "doc_ingest"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import logging  # noqa: E402

# Engines report degraded steps (a failed embedding batch, a skipped header) as warnings.
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


def load_env(path: Path = ROOT / ".env") -> None:
    """KEY=VALUE lines into os.environ; real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


class Rest:
    """PostgREST + Storage with the service role."""

    def __init__(self) -> None:
        url = os.environ.get("SUPABASE__URL", "http://127.0.0.1:54321").rstrip("/")
        key = os.environ["SUPABASE__SERVICE_ROLE_KEY"]
        self.rest, self.storage = f"{url}/rest/v1", f"{url}/storage/v1"
        self.h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        self.c = httpx.Client(timeout=120.0)

    def get(self, table: str, **params: str) -> list[dict[str, Any]]:
        r = self.c.get(f"{self.rest}/{table}", headers=self.h, params=params)
        r.raise_for_status()
        return r.json()

    def insert(self, table: str, rows: list[dict[str, Any]] | dict[str, Any], upsert: bool = False) -> None:
        headers = {**self.h, "Prefer": "resolution=merge-duplicates"} if upsert else self.h
        r = self.c.post(f"{self.rest}/{table}", headers=headers, json=rows)
        r.raise_for_status()

    def delete(self, table: str, **params: str) -> None:
        r = self.c.delete(f"{self.rest}/{table}", headers=self.h, params=params)
        r.raise_for_status()

    def rpc(self, fn: str, args: dict[str, Any]) -> list[dict[str, Any]]:
        r = self.c.post(f"{self.rest}/rpc/{fn}", headers=self.h, json=args)
        r.raise_for_status()
        return r.json()

    def upload(self, bucket: str, path: str, data: bytes, content_type: str) -> None:
        r = self.c.post(f"{self.storage}/object/{bucket}/{path}", content=data,
                        headers={**self.h, "Content-Type": content_type, "x-upsert": "true"})
        r.raise_for_status()


def vector(values: list[float] | None) -> str | None:
    return None if values is None else "[" + ",".join(f"{v:.7g}" for v in values) + "]"
