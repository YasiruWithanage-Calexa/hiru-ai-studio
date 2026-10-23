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
        self.entries.append(kwargs)


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

    async def record(self, row: Row) -> None:
        self.rows.append(row)

    async def tokens_since(self, since: datetime) -> int:
        return sum(r.get("input_tokens", 0) + r.get("output_tokens", 0) for r in self.rows)


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


class FakeLines(_Table):
    async def list(self, scene_id: UUID) -> list[Row]:  # type: ignore[override]
        return sorted((r for r in self.rows.values() if r["scene_id"] == str(scene_id)), key=lambda r: r["ord"])

    async def upsert(self, rows: list[Row]) -> None:
        for row in rows:
            self.rows.setdefault(row["id"], {}).update(row)


class FakeCanon(_Table):
    def __init__(self) -> None:
        super().__init__()
        self.version_rows: dict[str, Row] = {}

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


def build_fake_repos() -> Repos:
    profiles = FakeProfiles()
    members = FakeMembers(profiles)
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
    )
