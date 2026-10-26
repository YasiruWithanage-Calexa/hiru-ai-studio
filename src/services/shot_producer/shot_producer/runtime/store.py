"""Supabase access for shot_producer: scenes and shots in, designs and prompt versions out."""
from __future__ import annotations

from uuid import UUID

import httpx

from shot_producer.runtime.rest import Rest, Row

_CANON = ("id,kind,code,name,aliases,locked,"
          "current:canon_versions!canon_entities_current_version_fkey(version,card,wardrobe_anchor,voice_pin)")
_PERSONA = "id,name,specialty,style_note,charter"


def vector(values: list[float] | None) -> str | None:
    return None if values is None else "[" + ",".join(f"{v:.7g}" for v in values) + "]"


class Store:
    def __init__(self, rest: Rest) -> None:
        self.rest = rest

    # ── reading ──────────────────────────────────────────────────────────────────────────
    def production(self, production_id: UUID) -> Row | None:
        return self.rest.first("productions", {"id": f"eq.{production_id}",
                                               "select": "id,title,orientation,settings,summary"})

    def scenes(self, production_id: UUID, scene_ids: list[str]) -> list[Row]:
        if not scene_ids:
            return []
        return self.rest.select("scenes", {"production_id": f"eq.{production_id}",
                                           "id": f"in.({','.join(scene_ids)})",
                                           "select": "*,episode:episodes(number)", "order": "number"})

    def shots(self, scene_id: str) -> list[Row]:
        return self.rest.select("shots", {"scene_id": f"eq.{scene_id}", "select": "*", "order": "number"})

    def shot_scenes(self, production_id: UUID, shot_ids: list[str]) -> list[str]:
        if not shot_ids:
            return []
        rows = self.rest.select("shots", {"production_id": f"eq.{production_id}",
                                          "id": f"in.({','.join(shot_ids)})", "select": "scene_id"})
        return list(dict.fromkeys(str(r["scene_id"]) for r in rows))

    def lines(self, scene_id: str) -> list[Row]:
        return self.rest.select("dialogue_lines", {"scene_id": f"eq.{scene_id}", "select": "*", "order": "ord"})

    def canon(self, production_id: UUID) -> list[Row]:
        return self.rest.select("canon_entities", {"production_id": f"eq.{production_id}", "order": "code",
                                                   "select": _CANON})

    def lead_persona(self, production_id: UUID) -> Row | None:
        seat = self.rest.first("production_director_board", {"production_id": f"eq.{production_id}",
                                                              "seat": "eq.lead",
                                                              "select": f"persona:director_personas({_PERSONA})"})
        if seat and seat.get("persona"):
            return dict(seat["persona"])
        return self.rest.first("director_personas", {"slug": "eq.classic-teledrama", "select": _PERSONA})

    def accepted_frames(self, shot_ids: list[str]) -> dict[str, Row]:
        if not shot_ids:
            return {}
        rows = self.rest.select("first_frames", {"shot_id": f"in.({','.join(shot_ids)})",
                                                 "accepted_at": "not.is.null", "select": "id,shot_id,pins"})
        return {str(r["shot_id"]): r for r in rows}

    def last_prompt_version(self, shot_id: str) -> int:
        row = self.rest.first("video_prompts", {"shot_id": f"eq.{shot_id}", "select": "version",
                                                "order": "version.desc"})
        return int(row["version"]) if row else 0

    def techniques(self, query: str, embedding: list[float] | None, k: int = 4) -> list[Row]:
        """Intent → technique lookup (`match_craft_techniques`). Absent-safe: [] on any failure."""
        try:
            r = self.rest.client.post(f"{self.rest.rest}/rpc/match_craft_techniques", headers=self.rest.headers,
                                      json={"query_text": query, "query_embedding": vector(embedding),
                                            "match_domain": "", "match_categories": None, "match_count": k})
            r.raise_for_status()
            return list(r.json())
        except httpx.HTTPError:
            return []

    # ── writing ──────────────────────────────────────────────────────────────────────────
    def save_design(self, shot_id: str, ir: Row, design: Row) -> None:
        self.rest.patch("shots", {"id": f"eq.{shot_id}"}, {"ir": ir, "design": design})

    def add_prompt(self, row: Row) -> None:
        """A new prompt version; the shot moves to `prompt`. A version number taken meanwhile by
        another job is retried once with the next number."""
        try:
            self.rest.insert("video_prompts", [row])
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 409:
                raise
            row = {**row, "version": self.last_prompt_version(str(row["shot_id"])) + 1}
            self.rest.insert("video_prompts", [row])
        self.rest.patch("shots", {"id": f"eq.{row['shot_id']}"}, {"status": "prompt"})

    def audit(self, row: Row) -> None:
        try:
            self.rest.insert("audit_log", [row])
        except httpx.HTTPError:
            pass  # the audit trail never fails the change it records

    def record_usage(self, row: Row) -> None:
        try:
            self.rest.insert("token_usage", [row])
        except httpx.HTTPError:
            pass  # accounting must never fail the work it accounts for
