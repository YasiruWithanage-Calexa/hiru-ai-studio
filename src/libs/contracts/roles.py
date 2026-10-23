"""Who may do what. The ONE permission table (PLAN.md §9).

Two layers:
  * Workspace role (`profiles.app_role`): `admin` or `member`. An admin holds every permission
    on every production and is the only role that may manage members, settings and orientation
    (and so the only one that creates productions, since orientation is chosen at creation).
  * Production role (`production_members.role`): what a member may do inside one production.
    A member with no role on a production cannot see it at all.

The API enforces this table on every route. Postgres RLS enforces only visibility (a user reads
rows of productions they belong to); the browser writes nothing directly.
"""
from __future__ import annotations

from enum import StrEnum


class AppRole(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class ProductionRole(StrEnum):
    PRODUCER = "producer"
    DIRECTOR = "director"
    WRITER = "writer"
    PRODUCTION = "production"  # production crew: first frames, prompts, handoff
    REVIEWER = "reviewer"


class Permission(StrEnum):
    VIEW = "view"  # production, canon, shots, prompts
    COMMENT = "comment"  # comment / chat
    MANAGE_PRODUCTION = "manage_production"  # create; members, settings, orientation
    MANAGE_DOCUMENTS = "manage_documents"  # upload, confirm file roles, run structure build
    ANSWER_QUESTIONS = "answer_questions"  # live-build questions
    EDIT_SCRIPT = "edit_script"  # script & dialogue
    EDIT_CANON = "edit_canon"  # canon, locks, voice pins
    DIRECT = "direct"  # director chat edits, split scenes, shot lengths, director board
    GENERATE = "generate"  # first frames (generate / accept), video prompts
    HANDOFF = "handoff"  # copy / download bundle, upload takes
    APPROVE_SCENE = "approve_scene"  # lock a scene for production


P = Permission
_EVERYONE = frozenset({P.VIEW, P.COMMENT})

PRODUCTION_ROLE_PERMISSIONS: dict[ProductionRole, frozenset[Permission]] = {
    ProductionRole.PRODUCER: _EVERYONE
    | {
        P.MANAGE_DOCUMENTS, P.ANSWER_QUESTIONS, P.EDIT_SCRIPT, P.EDIT_CANON,
        P.DIRECT, P.GENERATE, P.HANDOFF, P.APPROVE_SCENE,
    },
    ProductionRole.DIRECTOR: _EVERYONE
    | {
        P.MANAGE_DOCUMENTS, P.ANSWER_QUESTIONS, P.EDIT_SCRIPT, P.EDIT_CANON,
        P.DIRECT, P.GENERATE, P.HANDOFF, P.APPROVE_SCENE,
    },
    ProductionRole.WRITER: _EVERYONE | {P.ANSWER_QUESTIONS, P.EDIT_SCRIPT},
    ProductionRole.PRODUCTION: _EVERYONE | {P.GENERATE, P.HANDOFF},
    ProductionRole.REVIEWER: _EVERYONE,
}

# Admin-only: no production role grants these, whatever it is.
ADMIN_ONLY: frozenset[Permission] = frozenset({P.MANAGE_PRODUCTION})


def permissions_for(
    app_role: AppRole | str, production_role: ProductionRole | str | None
) -> frozenset[Permission]:
    """Everything this person may do on one production."""
    if AppRole(app_role) is AppRole.ADMIN:
        return frozenset(Permission)
    if production_role is None:
        return frozenset()
    return PRODUCTION_ROLE_PERMISSIONS[ProductionRole(production_role)]


def can(
    app_role: AppRole | str,
    production_role: ProductionRole | str | None,
    permission: Permission,
) -> bool:
    return permission in permissions_for(app_role, production_role)
