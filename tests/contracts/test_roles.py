"""The permission table, checked cell by cell against PLAN.md §9.

The expected table is written out in full on purpose: a change to who may do what must show
up as a visible diff here, not as a quiet edit to a set expression in `contracts/roles.py`.
"""
import pytest

from contracts.roles import AppRole, Permission, ProductionRole, can, permissions_for

P = Permission
R = ProductionRole

EXPECTED: dict[Permission, set[ProductionRole]] = {
    P.VIEW: {R.PRODUCER, R.DIRECTOR, R.WRITER, R.PRODUCTION, R.REVIEWER},
    P.COMMENT: {R.PRODUCER, R.DIRECTOR, R.WRITER, R.PRODUCTION, R.REVIEWER},
    P.MANAGE_PRODUCTION: set(),  # admin only
    P.MANAGE_DOCUMENTS: {R.PRODUCER, R.DIRECTOR},
    P.ANSWER_QUESTIONS: {R.PRODUCER, R.DIRECTOR, R.WRITER},
    P.EDIT_SCRIPT: {R.PRODUCER, R.DIRECTOR, R.WRITER},
    P.EDIT_CANON: {R.PRODUCER, R.DIRECTOR},
    P.DIRECT: {R.PRODUCER, R.DIRECTOR},
    P.GENERATE: {R.PRODUCER, R.DIRECTOR, R.PRODUCTION},
    P.HANDOFF: {R.PRODUCER, R.DIRECTOR, R.PRODUCTION},
    P.APPROVE_SCENE: {R.PRODUCER, R.DIRECTOR},
}


def test_table_covers_every_permission():
    assert set(EXPECTED) == set(Permission)


@pytest.mark.parametrize("permission", list(Permission))
@pytest.mark.parametrize("role", list(ProductionRole))
def test_member_matrix(role, permission):
    assert can(AppRole.MEMBER, role, permission) == (role in EXPECTED[permission])


@pytest.mark.parametrize("permission", list(Permission))
@pytest.mark.parametrize("role", [None, *ProductionRole])
def test_admin_can_do_everything_with_or_without_a_role(role, permission):
    assert can(AppRole.ADMIN, role, permission)


def test_non_member_can_do_nothing():
    assert permissions_for(AppRole.MEMBER, None) == frozenset()


def test_producer_cannot_manage_members_settings_or_orientation():
    assert not can("member", "producer", P.MANAGE_PRODUCTION)


def test_unknown_role_is_rejected():
    with pytest.raises(ValueError):
        can("member", "owner", P.VIEW)
