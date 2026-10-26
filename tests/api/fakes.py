"""In-memory repositories with the same behaviour the API relies on from Supabase."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from api.repositories import Repos, Row


def _now() -> str:
    return datetime.now(UTC).isoformat()


class FakeProfiles:
    def __init__(self) -> None:
        self.rows: dict[str, Row] = {}

    def add(self, email: str, name: str, app_role: str = "member", active: bool = True) -> UUID:
        uid = uuid4()
        self.rows[str(uid)] = {"id": str(uid), "email": email, "display_name": name,
                               "app_role": app_role, "active": active}
        return uid

    async def get(self, user_id: UUID) -> Row | None:
        row = self.rows.get(str(user_id))
        return dict(row) if row else None

    async def get_by_email(self, email: str) -> Row | None:
        return next((dict(r) for r in self.rows.values() if r["email"] == email.lower()), None)

    async def list(self) -> list[Row]:
        return sorted((dict(r) for r in self.rows.values()), key=lambda r: r["display_name"])

    async def update(self, user_id: UUID, fields: Row) -> Row:
        self.rows[str(user_id)].update(fields)
        return dict(self.rows[str(user_id)])

    async def count_active_admins(self) -> int:
        return sum(1 for r in self.rows.values() if r["app_role"] == "admin" and r["active"])


class FakeProductions:
    def __init__(self, members: FakeMembers) -> None:
        self.rows: dict[str, Row] = {}
        self.members = members

    async def list_all(self) -> list[Row]:
        return sorted(self.rows.values(), key=lambda r: r["updated_at"], reverse=True)

    async def list_for_member(self, user_id: UUID) -> list[tuple[Row, str]]:
        out = [(self.rows[p], role) for (p, u), role in self.members.roles.items()
               if u == str(user_id) and p in self.rows]
        return sorted(out, key=lambda pr: pr[0]["updated_at"], reverse=True)

    async def get(self, production_id: UUID) -> Row | None:
        return self.rows.get(str(production_id))

    async def get_with_role(self, production_id: UUID, user_id: UUID) -> tuple[Row, str | None] | None:
        row = self.rows.get(str(production_id))
        return (row, self.members.roles.get((str(production_id), str(user_id)))) if row else None

    async def create(self, fields: Row) -> Row:
        pid = str(uuid4())
        row = {"id": pid, "status": "draft", "summary": "", "settings": {}, "kind": "drama_series",
               "created_at": _now(), "updated_at": _now(), **fields}
        self.rows[pid] = row
        return row

    async def update(self, production_id: UUID, fields: Row) -> Row:
        row = self.rows[str(production_id)]
        row.update(fields)
        row["updated_at"] = _now()
        return row


class FakeMembers:
    def __init__(self, profiles: FakeProfiles) -> None:
        self.roles: dict[tuple[str, str], str] = {}
        self.profiles = profiles

    async def role_of(self, production_id: UUID, user_id: UUID) -> str | None:
        return self.roles.get((str(production_id), str(user_id)))

    async def list(self, production_id: UUID) -> list[Row]:
        out = []
        for (p, u), role in self.roles.items():
            if p == str(production_id):
                prof = self.profiles.rows[u]
                out.append({"user_id": u, "role": role, "display_name": prof["display_name"],
                            "email": prof["email"], "active": prof["active"]})
        return out

    async def upsert(self, production_id: UUID, user_id: UUID, role: str, added_by: UUID) -> Row:
        self.roles[(str(production_id), str(user_id))] = role
        return {"production_id": str(production_id), "user_id": str(user_id), "role": role}

    async def delete(self, production_id: UUID, user_id: UUID) -> bool:
        return self.roles.pop((str(production_id), str(user_id)), None) is not None


class FakeInvitations:
    def __init__(self) -> None:
        self.rows: dict[str, Row] = {}

    async def create(self, fields: Row) -> Row:
        iid = str(uuid4())
        self.rows[iid] = {"id": iid, "accepted_at": None, **fields}
        return self.rows[iid]

    async def delete(self, invitation_id: UUID) -> None:
        self.rows.pop(str(invitation_id), None)

    async def list_pending(self) -> list[Row]:
        return [r for r in self.rows.values() if r["accepted_at"] is None]


class FakeAuthAdmin:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.fail = False

    async def invite(self, email: str, redirect_to: str, data: Row) -> None:
        if self.fail:
            raise RuntimeError("smtp down")
        self.sent.append(email)


class FakeAudit:
    def __init__(self) -> None:
        self.entries: list[Row] = []

    async def record(self, **kwargs: Any) -> None:
        self.entries.append({"id": len(self.entries) + 1, "created_at": _now(), **kwargs})

    async def list(self, production_id: UUID, limit: int = 100) -> list[Row]:
        rows = [{**e, "actor_user_id": str(e["actor_user_id"]) if e.get("actor_user_id") else None,
                 "production_id": str(e["production_id"]) if e.get("production_id") else None,
                 "diff": e.get("diff") or {}, "actor_agent": e.get("actor_agent")}
                for e in self.entries if str(e.get("production_id")) == str(production_id)]
        return list(reversed(rows))[:limit]


class FakeJobs:
    def __init__(self) -> None:
        self.rows: dict[str, Row] = {}
        self.event_rows: list[Row] = []

    async def create(self, fields: Row) -> Row:
        row = {"result": None, "error": None, "cursor": 0, "created_at": _now(), "updated_at": _now(), **fields}
        self.rows[fields["id"]] = row
        return row

    async def get(self, job_id: UUID) -> Row | None:
        return self.rows.get(str(job_id))

    async def mark_failed(self, job_id: UUID, error: str) -> None:
        self.rows[str(job_id)].update(status="failed", error=error)

    async def events(self, job_id: UUID, after_seq: int = 0) -> list[Row]:
        return [e for e in self.event_rows if e["job_id"] == str(job_id) and e["seq"] > after_seq]

    async def latest(self, production_id: UUID, kind: str) -> Row | None:
        rows = [r for r in self.rows.values() if r.get("production_id") == str(production_id) and r["kind"] == kind]
        return rows[-1] if rows else None

    async def advance(self, job_id: UUID, from_cursor: int, request: Row | None = None) -> bool:
        row = self.rows.get(str(job_id))
        if row is None or int(row.get("cursor", 0)) != from_cursor or row["status"] not in ("running", "pending"):
            return False
        row["cursor"] = from_cursor + 1
        if request is not None:
            row["request"] = request
        return True

    async def claim_resume(self, job_id: UUID) -> bool:
        row = self.rows.get(str(job_id))
        if row is None or row["status"] != "waiting_input":
            return False
        row["status"] = "running"
        return True

    def add_event(self, job_id: str, type_: str, payload: Row, agent: str | None = None) -> None:
        self.event_rows.append({"job_id": job_id, "seq": len(self.event_rows) + 1, "type": type_,
                                "agent": agent, "payload": payload, "created_at": _now()})


class FakeDocuments:
    def __init__(self) -> None:
        self.rows: dict[str, Row] = {}

    async def create(self, fields: Row) -> Row:
        row = {"detected_role": None, "role_confidence": None, "role_reason": "", "confirmed_role": None,
               "page_count": None, "char_count": None, "chunk_count": 0, "warnings": [], "error": None,
               "created_at": _now(), "updated_at": _now(), **fields}
        self.rows[fields["id"]] = row
        return row

    async def get(self, production_id: UUID, document_id: UUID) -> Row | None:
        row = self.rows.get(str(document_id))
        return row if row and row["production_id"] == str(production_id) else None

    async def find_by_hash(self, production_id: UUID, sha256: str) -> Row | None:
        return next((r for r in self.rows.values()
                     if r["production_id"] == str(production_id) and r["sha256"] == sha256), None)

    async def list(self, production_id: UUID) -> list[Row]:
        return [r for r in self.rows.values() if r["production_id"] == str(production_id)]

    async def update(self, document_id: UUID, fields: Row) -> Row:
        self.rows[str(document_id)].update(fields)
        return self.rows[str(document_id)]

    async def delete(self, document_id: UUID) -> None:
        self.rows.pop(str(document_id), None)


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    async def upload(self, bucket: str, path: str, data: bytes, content_type: str) -> None:
        self.objects[(bucket, path)] = data

    async def remove(self, bucket: str, path: str) -> None:
        self.objects.pop((bucket, path), None)

    async def download(self, bucket: str, path: str) -> bytes:
        return self.objects[(bucket, path)]


class FakeSearch:
    def __init__(self) -> None:
        self.calls: list[Row] = []
        self.chunk_rows: list[Row] = []
        self.technique_rows: list[Row] = []

    async def match_chunks(self, **kwargs: Any) -> list[Row]:
        self.calls.append(kwargs)
        return self.chunk_rows[: kwargs["match_count"]]

    async def match_techniques(self, **kwargs: Any) -> list[Row]:
        self.calls.append(kwargs)
        return self.technique_rows


class FakeUsage:
    def __init__(self) -> None:
        self.rows: list[Row] = []
        self.budgets: dict[str, int] = {}

    async def record(self, row: Row) -> None:
        self.rows.append(row)

    async def tokens_since(self, since: datetime) -> int:
        return sum(r.get("input_tokens", 0) + r.get("output_tokens", 0) for r in self.rows)

    async def budget(self, month: str) -> int | None:
        return self.budgets.get(month)

    async def set_budget(self, month: str, tokens: int, user_id: UUID) -> None:
        self.budgets[month] = tokens


class _Table:
    """A dict of rows scoped by production, enough for the structure repos."""

    def __init__(self) -> None:
        self.rows: dict[str, Row] = {}

    def add(self, **fields: Any) -> Row:
        row = {"id": str(uuid4()), "created_at": _now(), "updated_at": _now(), **fields}
        self.rows[row["id"]] = row
        return row

    def _scoped(self, production_id: UUID) -> list[Row]:
        return [r for r in self.rows.values() if r["production_id"] == str(production_id)]

    async def get(self, production_id: UUID, row_id: UUID) -> Row | None:
        row = self.rows.get(str(row_id))
        return row if row and row["production_id"] == str(production_id) else None

    async def update(self, row_id: UUID, fields: Row) -> Row:
        self.rows[str(row_id)].update(fields)
        return self.rows[str(row_id)]


class FakeEpisodes(_Table):
    async def list(self, production_id: UUID) -> list[Row]:
        return sorted(self._scoped(production_id), key=lambda r: r["number"])


class FakeScenes(_Table):
    async def list(self, production_id: UUID, episode_id: UUID | None = None) -> list[Row]:
        rows = [r for r in self._scoped(production_id) if episode_id is None or r["episode_id"] == str(episode_id)]
        return sorted(rows, key=lambda r: r["number"])


class FakeShots(_Table):
    async def list(self, production_id: UUID, scene_id: UUID | None = None) -> list[Row]:
        rows = [r for r in self._scoped(production_id) if scene_id is None or r["scene_id"] == str(scene_id)]
        return sorted(rows, key=lambda r: r["number"])

    async def save_plan(self, shots: list[Row], removed: list[str]) -> None:
        for sid in removed:
            self.rows.pop(sid, None)
        for row in shots:
            self.rows.setdefault(row["id"], {"created_at": _now()}).update(row)
        numbers = [(r["scene_id"], r["number"]) for r in self.rows.values()]
        assert len(numbers) == len(set(numbers)), "shot numbers must be unique per scene"


class FakeLines(_Table):
    async def list(self, scene_id: UUID) -> list[Row]:  # type: ignore[override]
        return sorted((r for r in self.rows.values() if r["scene_id"] == str(scene_id)), key=lambda r: r["ord"])

    async def list_for_production(self, production_id: UUID) -> list[Row]:
        return [r for r in self.rows.values() if r.get("production_id") == str(production_id)]

    async def upsert(self, rows: list[Row]) -> None:
        for row in rows:
            self.rows.setdefault(row["id"], {}).update(row)
        ords = [(r["scene_id"], r["ord"]) for r in self.rows.values()]
        assert len(ords) == len(set(ords)), "line order must be unique per scene"

    async def delete(self, line_ids: list[str]) -> None:
        for lid in line_ids:
            self.rows.pop(lid, None)


class FakePersonas:
    def __init__(self) -> None:
        self.rows: dict[str, Row] = {}
        for slug, name in (("grounded-realist", "Grounded Realist"), ("classic-teledrama", "Classic Teledrama"),
                           ("tension-builder", "Tension Builder"), ("short-form", "Short-Form Storyteller"),
                           ("lyrical-eye", "Lyrical Eye")):
            pid = str(uuid4())
            self.rows[pid] = {"id": pid, "slug": slug, "name": name, "initials": name[:2].upper(), "color": "#2F3A45",
                              "specialty": "", "traits": [{"label": "Realism", "value": 50}], "style_note": "",
                              "charter": f"{name} charter", "active": True}

    def by_slug(self, slug: str) -> Row:
        return next(r for r in self.rows.values() if r["slug"] == slug)

    async def list(self) -> list[Row]:
        return sorted((r for r in self.rows.values() if r["active"]), key=lambda r: r["name"])

    async def get_many(self, persona_ids: list[UUID]) -> list[Row]:
        return [self.rows[str(p)] for p in persona_ids if str(p) in self.rows]


class FakeBoard:
    def __init__(self, personas: FakePersonas) -> None:
        self.seats: dict[str, list[Row]] = {}
        self.personas = personas

    async def list(self, production_id: UUID) -> list[Row]:
        return [{**s, "persona": self.personas.rows[s["persona_id"]]} for s in self.seats.get(str(production_id), [])]

    async def replace(self, production_id: UUID, seats: list[Row], added_by: UUID) -> None:
        self.seats[str(production_id)] = [{"persona_id": str(s["persona_id"]), "seat": s["seat"]} for s in seats]


class FakeThreads(_Table):
    async def list(self, production_id: UUID, scene_id: UUID | None = None) -> list[Row]:
        rows = [r for r in self._scoped(production_id) if scene_id is None or r["scene_id"] == str(scene_id)]
        return sorted(rows, key=lambda r: r["created_at"])

    async def create(self, fields: Row) -> Row:
        return self.add(**{"title": "", **fields})

    async def touch(self, thread_id: UUID) -> None:
        self.rows[str(thread_id)]["updated_at"] = _now()


class FakeMessages(_Table):
    async def list(self, thread_id: UUID, limit: int = 100) -> list[Row]:  # type: ignore[override]
        rows = [r for r in self.rows.values() if r["thread_id"] == str(thread_id)]
        return rows[-limit:]

    async def create(self, fields: Row) -> Row:
        return self.add(**{"blocks": [], "ops": [], "citations": [], "text": "", "speaker": "", "tone": None,
                           "persona_id": None, "author_user_id": None, **fields})


class FakeMemory(_Table):
    def __init__(self) -> None:
        super().__init__()
        self.chunks: dict[str, Row] = {}  # source → chunk

    async def list(self, production_id: UUID, scene_id: UUID | None = None) -> list[Row]:
        rows = [r for r in self._scoped(production_id) if scene_id is None or r.get("scene_id") == str(scene_id)]
        return sorted(rows, key=lambda r: r["created_at"], reverse=True)

    async def add(self, item: Row, embedding: list[float] | None, embedding_model: str) -> Row:  # type: ignore[override]
        row = self.add_row(item)
        self.chunks[f"memory:{row['id']}"] = {"corpus": "memory", "production_id": row["production_id"],
                                              "content": row["text"], "embedding": embedding}
        return row

    def add_row(self, item: Row) -> Row:
        return super().add(**{"source_ref": {}, "scene_id": None, "created_by": None, **item})

    async def delete(self, item_id: UUID) -> None:
        self.rows.pop(str(item_id), None)
        self.chunks.pop(f"memory:{item_id}", None)


class FakeCanon(_Table):
    def __init__(self) -> None:
        super().__init__()
        self.version_rows: dict[str, Row] = {}

    async def create(self, fields: Row) -> Row:
        return self.add(**{"locked": False, "core": False, "aliases": [], "current_version_id": None, **fields})

    def _with_current(self, row: Row) -> Row:
        return {**row, "current": self.version_rows.get(str(row.get("current_version_id")))}

    async def list(self, production_id: UUID) -> list[Row]:
        return [self._with_current(r) for r in sorted(self._scoped(production_id), key=lambda r: r["code"])]

    async def get(self, production_id: UUID, entity_id: UUID) -> Row | None:
        row = await super().get(production_id, entity_id)
        return self._with_current(row) if row else None

    async def versions(self, entity_id: UUID) -> list[Row]:
        rows = [v for v in self.version_rows.values() if v["entity_id"] == str(entity_id)]
        return sorted(rows, key=lambda v: -v["version"])

    async def add_version(self, entity_id: UUID, version: Row) -> Row:
        row = {"id": str(uuid4()), "created_at": _now(), "reference_assets": [], **version}
        self.version_rows[row["id"]] = row
        self.rows[str(entity_id)]["current_version_id"] = row["id"]
        return row


class FakeQuestions(_Table):
    async def list(self, production_id: UUID, status: str | None = None) -> list[Row]:
        return [r for r in self._scoped(production_id) if status is None or r["status"] == status]

    async def answer(self, question_id: UUID, answer: Row, user_id: UUID) -> Row | None:
        row = self.rows.get(str(question_id))
        if row is None or row["status"] != "open":
            return None
        row.update(status="answered", answer=answer, answered_by=str(user_id), answered_at=_now())
        return row

    async def open_count(self, job_id: UUID) -> int:
        return sum(1 for r in self.rows.values() if r.get("job_id") == str(job_id) and r["status"] == "open")


class FakeFrames(_Table):
    async def create_many(self, rows: list[Row]) -> None:
        for row in rows:
            self.rows[row["id"]] = {"created_at": _now(), "accepted_at": None, "accepted_by": None, "pins": {},
                                    "storage_path": None, "error": None, "rejected_reason": None, "prompt": "",
                                    "reference_ids": [], **row}

    async def list_for_shots(self, shot_ids: list[str]) -> list[Row]:
        return sorted((r for r in self.rows.values() if r["shot_id"] in shot_ids), key=lambda r: r["created_at"])

    async def update_many(self, frame_ids: list[str], fields: Row) -> None:
        for fid in frame_ids:
            self.rows[fid].update(fields)

    async def accept(self, shot_id: UUID, frame_id: UUID, user_id: UUID) -> bool:
        row = self.rows[str(frame_id)]
        if row["status"] != "done":
            return False
        for other in self.rows.values():
            if other["shot_id"] == str(shot_id):
                other.update(accepted_at=None, accepted_by=None)
        row.update(accepted_at=_now(), accepted_by=str(user_id))
        return True

    async def unaccept(self, frame_id: UUID) -> None:
        self.rows[str(frame_id)].update(accepted_at=None, accepted_by=None)


class FakePrompts(_Table):
    async def latest_for_shots(self, shot_ids: list[str]) -> dict[str, Row]:
        out: dict[str, Row] = {}
        for row in sorted(self.rows.values(), key=lambda r: -r["version"]):
            if row["shot_id"] in shot_ids:
                out.setdefault(row["shot_id"], row)
        return out

    async def list(self, shot_id: UUID) -> list[Row]:  # type: ignore[override]
        return sorted((r for r in self.rows.values() if r["shot_id"] == str(shot_id)), key=lambda r: -r["version"])


class FakeTakes(_Table):
    async def create(self, row: Row) -> Row:
        full = {"created_at": _now(), "status": "uploaded", "reason": None, "duration_s": None,
                "last_frame_path": None, "accepted_at": None, "accepted_by": None, **row}
        self.rows[full["id"]] = full
        return full

    async def list_for_shots(self, shot_ids: list[str]) -> list[Row]:
        return sorted((r for r in self.rows.values() if r["shot_id"] in shot_ids), key=lambda r: r["created_at"])

    async def accept(self, shot_id: UUID, take_id: UUID, user_id: UUID) -> bool:
        for other in self.rows.values():
            if other["shot_id"] == str(shot_id) and other["status"] == "accepted":
                other.update(status="uploaded", accepted_at=None, accepted_by=None)
        self.rows[str(take_id)].update(status="accepted", accepted_at=_now(), accepted_by=str(user_id), reason=None)
        return True


def build_fake_repos() -> Repos:
    profiles = FakeProfiles()
    members = FakeMembers(profiles)
    personas = FakePersonas()
    return Repos(
        profiles=profiles,
        productions=FakeProductions(members),
        members=members,
        invitations=FakeInvitations(),
        auth_admin=FakeAuthAdmin(),
        audit=FakeAudit(),
        jobs=FakeJobs(),
        documents=FakeDocuments(),
        storage=FakeStorage(),
        search=FakeSearch(),
        usage=FakeUsage(),
        episodes=FakeEpisodes(),
        scenes=FakeScenes(),
        shots=FakeShots(),
        lines=FakeLines(),
        canon=FakeCanon(),
        questions=FakeQuestions(),
        personas=personas,
        board=FakeBoard(personas),
        threads=FakeThreads(),
        messages=FakeMessages(),
        memory=FakeMemory(),
        frames=FakeFrames(),
        prompts=FakePrompts(),
        takes=FakeTakes(),
    )
