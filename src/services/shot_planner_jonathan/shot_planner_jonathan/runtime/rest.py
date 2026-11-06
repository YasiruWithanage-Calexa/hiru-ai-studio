"""Supabase PostgREST + Storage over HTTP with the service role. Vendored per service
(PLAN.md §4): identical in every function that needs it, imported by nothing outside it."""
from __future__ import annotations

from typing import Any

import httpx

Row = dict[str, Any]
_BATCH = 200


def _ok(r: httpx.Response) -> None:
    """raise_for_status, with what PostgREST said: a bare "400 Bad Request" hides a missing column or a bad value."""
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise httpx.HTTPStatusError(f"{error}\nSupabase said: {r.text[:500]}",
                                    request=error.request, response=error.response) from None


class Rest:
    def __init__(self, url: str, service_role_key: str, client: httpx.Client | None = None) -> None:
        base = url.rstrip("/")
        self.rest = f"{base}/rest/v1"
        self.storage = f"{base}/storage/v1"
        self.client = client or httpx.Client(timeout=60.0)
        self.headers = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}",
                        "Content-Type": "application/json"}

    def select(self, table: str, params: dict[str, str]) -> list[Row]:
        r = self.client.get(f"{self.rest}/{table}", headers=self.headers, params=params)
        _ok(r)
        return list(r.json())

    def first(self, table: str, params: dict[str, str]) -> Row | None:
        rows = self.select(table, {**params, "limit": "1"})
        return rows[0] if rows else None

    def insert(self, table: str, rows: list[Row]) -> None:
        for i in range(0, len(rows), _BATCH):
            r = self.client.post(f"{self.rest}/{table}", headers=self.headers, json=rows[i: i + _BATCH])
            _ok(r)

    def upsert(self, table: str, rows: list[Row], on_conflict: str = "id") -> None:
        """Insert or merge. Every row in one call must have the same keys (PostgREST rule)."""
        headers = {**self.headers, "Prefer": "resolution=merge-duplicates"}
        for i in range(0, len(rows), _BATCH):
            r = self.client.post(f"{self.rest}/{table}", headers=headers,
                                 params={"on_conflict": on_conflict}, json=rows[i: i + _BATCH])
            _ok(r)

    def patch(self, table: str, params: dict[str, str], fields: Row) -> None:
        r = self.client.patch(f"{self.rest}/{table}", headers=self.headers, params=params, json=fields)
        _ok(r)

    def delete(self, table: str, params: dict[str, str]) -> None:
        r = self.client.delete(f"{self.rest}/{table}", headers=self.headers, params=params)
        _ok(r)

    def download(self, bucket: str, path: str) -> bytes:
        r = self.client.get(f"{self.storage}/object/{bucket}/{path}", headers=self.headers)
        _ok(r)
        return r.content
