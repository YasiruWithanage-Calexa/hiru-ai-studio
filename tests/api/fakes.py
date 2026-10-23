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
        row = {"result": None, "error": None, "created_at": _now(), "updated_at": _now(), **fields}
        self.rows[fields["id"]] = row
        return row

    async def get(self, job_id: UUID) -> Row | None:
        return self.rows.get(str(job_id))

    async def mark_failed(self, job_id: UUID, error: str) -> None:
        self.rows[str(job_id)].update(status="failed", error=error)

    async def events(self, job_id: UUID, after_seq: int = 0) -> list[Row]:
        return [e for e in self.event_rows if e["job_id"] == str(job_id) and e["seq"] > after_seq]


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
    )
