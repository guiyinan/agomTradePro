"""Pure Domain contracts for explicit single-owner policy facts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta, timezone
from typing import cast

import pytest

from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.single_owner_authority_policy_v1 import (
    ACTIVE_STATUS,
    APPROVER_ROLE,
    ARTIFACT_TYPE,
    CLAIMANT_ROLE,
    MODE,
    REVOKED_STATUS,
    SCHEMA,
    SingleOwnerAuthorityPolicyV1,
    validate_single_owner_participants,
    validate_single_owner_policy_successor,
)

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)
VALID_UNTIL = NOW + timedelta(hours=1)


def test_successor_supports_explicit_revocation_without_changing_scope() -> None:
    previous = _policy()
    successor = _policy(
        policy_version="2", status="revoked", observed_at=NOW + timedelta(minutes=1)
    )
    validate_single_owner_policy_successor(previous, successor)
    assert successor.content_hash != previous.content_hash
    assert not successor.is_current_at(successor.observed_at)


@pytest.mark.parametrize(
    "field,value",
    [
        ("policy_id", "different-policy"),
        ("tenant_id", "different-tenant"),
        ("owner_id", "different-owner"),
        ("account_namespace", "other"),
        ("account_id", "different-account"),
        ("owner_user_id", 18),
    ],
)
def test_successor_cannot_reassign_an_existing_policy_scope(field: str, value: object) -> None:
    successor = _policy(
        policy_version="2", observed_at=NOW + timedelta(minutes=1), **{field: value}
    )
    with pytest.raises(ValueError, match="changed"):
        validate_single_owner_policy_successor(_policy(), successor)


def test_successor_requires_a_new_version_and_later_observation() -> None:
    with pytest.raises(ValueError, match="version"):
        validate_single_owner_policy_successor(
            _policy(), _policy(observed_at=NOW + timedelta(minutes=1))
        )
    with pytest.raises(ValueError, match="observation"):
        validate_single_owner_policy_successor(_policy(), _policy(policy_version="2"))


def _policy(**changes: object) -> SingleOwnerAuthorityPolicyV1:
    """Build a valid policy fixture while allowing one explicit mutation."""

    values: dict[str, object] = {
        "policy_id": "personal-project",
        "policy_version": "1",
        "tenant_id": "tenant-a",
        "owner_id": "owner-a",
        "account_namespace": "account",
        "account_id": "account-a",
        "owner_user_id": 17,
        "authorization_content_hash": "a" * 64,
        "observed_at": NOW,
        "valid_from": NOW,
        "valid_until": VALID_UNTIL,
    }
    values.update(changes)
    return SingleOwnerAuthorityPolicyV1(**values)  # type: ignore[arg-type]


def _participants() -> tuple[AccountOwnerAssignmentActor, AccountOwnerAssignmentActor]:
    """Build the same real staff actor under the two server role projections."""

    return (
        AccountOwnerAssignmentActor("django-user:17", 17, CLAIMANT_ROLE, is_staff=True),
        AccountOwnerAssignmentActor("django-user:17", 17, APPROVER_ROLE, is_staff=True),
    )


def test_policy_defaults_active_and_emits_golden_canonical_hashes() -> None:
    policy = _policy()

    assert policy.status == ACTIVE_STATUS
    assert policy.to_payload() == {
        "account_id": "account-a",
        "account_namespace": "account",
        "artifact_type": ARTIFACT_TYPE,
        "authorization_content_hash": "a" * 64,
        "content_hash": "5a19250f75caf53db787d615dae962a67e46832c81725d58c62a2caa50763c63",
        "identity_hash": "cfcb940bddb9eccd631226849ed40f9ce3edb869deca0205689f3798781964bc",
        "mode": MODE,
        "owner_id": "owner-a",
        "owner_user_id": 17,
        "observed_at": "2026-09-10T12:00:00.000000Z",
        "policy_id": "personal-project",
        "policy_version": "1",
        "schema": SCHEMA,
        "status": ACTIVE_STATUS,
        "tenant_id": "tenant-a",
        "valid_from": "2026-09-10T12:00:00.000000Z",
        "valid_until": "2026-09-10T13:00:00.000000Z",
    }


def test_equivalent_offset_datetimes_have_one_utc_canonical_hash() -> None:
    offset = timezone(timedelta(hours=8))
    policy = _policy(
        observed_at=datetime(2026, 9, 10, 20, tzinfo=offset),
        valid_from=datetime(2026, 9, 10, 20, tzinfo=offset),
        valid_until=datetime(2026, 9, 10, 21, tzinfo=offset),
    )

    assert policy.to_payload()["observed_at"] == "2026-09-10T12:00:00.000000Z"
    assert policy.to_payload()["valid_until"] == "2026-09-10T13:00:00.000000Z"
    assert policy.content_hash == _policy().content_hash


def test_policy_is_frozen_and_current_only_inside_active_window() -> None:
    policy = _policy()

    assert policy.is_current_at(NOW) is True
    assert policy.is_current_at(VALID_UNTIL - timedelta(microseconds=1)) is True
    assert policy.is_current_at(VALID_UNTIL) is False
    assert policy.is_current_at(NOW - timedelta(microseconds=1)) is False
    assert _policy(status=REVOKED_STATUS).is_current_at(NOW) is False

    with pytest.raises(FrozenInstanceError):
        policy.status = REVOKED_STATUS  # type: ignore[misc]


def test_policy_is_not_current_before_its_observation_clock() -> None:
    policy = _policy(valid_from=NOW - timedelta(hours=1))

    assert policy.is_current_at(NOW - timedelta(microseconds=1)) is False
    assert policy.is_current_at(NOW) is True


@pytest.mark.parametrize(
    "changes",
    [
        {"valid_from": NOW + timedelta(seconds=1)},
        {"observed_at": VALID_UNTIL},
        {"observed_at": datetime(2026, 9, 10, 12)},
        {"valid_from": date(2026, 9, 10)},
        {"valid_until": "2026-09-10T13:00:00Z"},
    ],
)
def test_policy_rejects_invalid_clock_types_and_order(changes: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        _policy(**changes)


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_user_id", True),
        ("owner_user_id", 0),
        ("authorization_content_hash", "A" * 64),
        ("authorization_content_hash", "not-a-hash"),
        ("status", "pending"),
        ("status", cast(str, 1)),
        ("schema", "other.schema"),
        ("artifact_type", "other_artifact"),
        ("mode", "team"),
    ],
)
def test_policy_rejects_invalid_identity_source_and_fixed_fields(
    field: str,
    value: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _policy(**{field: value})


def test_policy_rejects_modified_identity_content_and_source_hashes() -> None:
    policy = _policy()

    with pytest.raises(ValueError, match="identity_hash"):
        replace(policy, identity_hash="b" * 64)
    with pytest.raises(ValueError, match="content_hash"):
        replace(policy, content_hash="b" * 64)
    with pytest.raises(ValueError, match="content_hash"):
        replace(policy, authorization_content_hash="b" * 64)
    with pytest.raises(ValueError, match="content_hash"):
        replace(policy, owner_id="owner-b")


def test_single_owner_validation_accepts_same_real_staff_actor_in_both_roles() -> None:
    claimant, approver = _participants()

    assert validate_single_owner_participants(_policy(), claimant, approver, NOW) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"claimant": AccountOwnerAssignmentActor("other", 17, CLAIMANT_ROLE, is_staff=True)},
        {
            "approver": AccountOwnerAssignmentActor(
                "django-user:17", 18, APPROVER_ROLE, is_staff=True
            )
        },
        {"claimant": AccountOwnerAssignmentActor("django-user:17", 17, "wrong", is_staff=True)},
        {"approver": AccountOwnerAssignmentActor("django-user:17", 17, "wrong", is_staff=True)},
        {"claimant": AccountOwnerAssignmentActor("django-user:17", 17, CLAIMANT_ROLE)},
        {
            "claimant": AccountOwnerAssignmentActor("django-user:17", 17, CLAIMANT_ROLE),
            "approver": AccountOwnerAssignmentActor(
                "django-user:17", 17, APPROVER_ROLE, is_staff=False
            ),
        },
    ],
)
def test_single_owner_validation_rejects_identity_roles_and_staff_substitution(
    changes: dict[str, AccountOwnerAssignmentActor],
) -> None:
    claimant, approver = _participants()
    claimant = changes.get("claimant", claimant)
    approver = changes.get("approver", approver)

    with pytest.raises(ValueError):
        validate_single_owner_participants(_policy(), claimant, approver, NOW)


def test_single_owner_validation_rejects_owner_mismatch_and_noncurrent_policy() -> None:
    claimant, approver = _participants()

    with pytest.raises(ValueError, match="owner_user_id"):
        validate_single_owner_participants(_policy(owner_user_id=18), claimant, approver, NOW)
    with pytest.raises(ValueError, match="current"):
        validate_single_owner_participants(_policy(status=REVOKED_STATUS), claimant, approver, NOW)
    with pytest.raises(ValueError, match="current"):
        validate_single_owner_participants(
            _policy(), claimant, approver, NOW - timedelta(microseconds=1)
        )


@pytest.mark.parametrize(
    "argument",
    [
        (object(), _participants()[1], _policy(), NOW),
        (_policy(), object(), _participants()[1], NOW),
        (_policy(), _participants()[0], object(), NOW),
        (_policy(), _participants()[0], _participants()[1], datetime(2026, 9, 10, 12)),
    ],
)
def test_single_owner_validation_requires_exact_typed_injected_facts(
    argument: tuple[object, object, object, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        validate_single_owner_participants(*argument)  # type: ignore[arg-type]


__all__ = [
    "test_policy_defaults_active_and_emits_golden_canonical_hashes",
    "test_single_owner_validation_accepts_same_real_staff_actor_in_both_roles",
]
