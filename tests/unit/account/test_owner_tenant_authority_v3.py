"""Unit contracts for the explicit long-lived owner authority V3 Domain."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.account_owner_assignment_evidence_v4 import (
    AccountOwnerAssignmentEvidenceV4,
)
from apps.account.domain.account_owner_assignment_evidence_v5 import (
    AccountOwnerAssignmentEvidenceV5,
)
from apps.account.domain.owner_tenant_authority_v3 import (
    APPROVER_ROLE,
    ARTIFACT_TYPE,
    AUTHORITY_V3_CONTENT_HASH_DOMAIN,
    AUTHORITY_V3_IDENTITY_HASH_DOMAIN,
    MUST_NOT_EXECUTE,
    OWNER,
    PERMISSION,
    REVOCATION_ARTIFACT_TYPE,
    REVOCATION_SCHEMA,
    REVOCATION_V3_CONTENT_HASH_DOMAIN,
    REVOCATION_V3_IDENTITY_HASH_DOMAIN,
    REVOKER_ROLE,
    SCHEMA,
    STATUS,
    OwnerTenantAuthorityV3,
    OwnerTenantAuthorityV3Revocation,
    validate_owner_tenant_authority_v3_revocation,
    validate_owner_tenant_authority_v3_root,
    validate_owner_tenant_authority_v3_successor,
)
from tests.unit.account.test_account_owner_assignment_evidence_v5 import _evidence


def _authority(
    assignment: AccountOwnerAssignmentEvidenceV5 | None = None,
    **changes: object,
) -> OwnerTenantAuthorityV3:
    """Build one valid V3 root from the exact Evidence V5 fixture."""

    value = assignment or _evidence()
    claimant = value.claimant
    approved_at = value.recorded_at + timedelta(minutes=1)
    recorded_at = approved_at + timedelta(minutes=1)
    values: dict[str, object] = {
        "authority_id": "authority-v3-7",
        "authority_version": "v3.1",
        "assignment": value,
        "policy": value.policy,
        "approved_by": AccountOwnerAssignmentActor(
            claimant.actor_id,
            claimant.user_id,
            APPROVER_ROLE,
            kind="human",
            is_staff=True,
        ),
        "approved_at": approved_at,
        "recorded_at": recorded_at,
        "valid_until": datetime(2026, 8, 20, 12, tzinfo=UTC),
    }
    values.update(changes)
    return OwnerTenantAuthorityV3(**values)  # type: ignore[arg-type]


def _successor(previous: OwnerTenantAuthorityV3, **changes: object) -> OwnerTenantAuthorityV3:
    """Build one exact same-scope V3 successor before the upstream TTL ends."""

    values: dict[str, object] = {
        "authority_version": "v3.2",
        "approved_at": previous.approved_at + timedelta(minutes=1),
        "recorded_at": previous.recorded_at + timedelta(minutes=1),
        "valid_until": previous.valid_until,
        "supersedes_content_hash": previous.content_hash,
        "identity_hash": "",
        "content_hash": "",
    }
    values.update(changes)
    return replace(previous, **values)


def _revocation(
    authority: OwnerTenantAuthorityV3 | None = None,
    **changes: object,
) -> OwnerTenantAuthorityV3Revocation:
    """Build one valid same-owner V3 revocation event."""

    value = authority or _authority()
    values: dict[str, object] = {
        "authority_content_hash": value.content_hash,
        "policy_content_hash": value.policy.content_hash,
        "revoked_by": AccountOwnerAssignmentActor(
            value.actor_id,
            value.actor_user_id,
            REVOKER_ROLE,
            kind="human",
            is_staff=True,
        ),
        "revoked_at": value.valid_until + timedelta(minutes=1),
        "recorded_at": value.valid_until + timedelta(minutes=1),
        "reason": "owner-request",
    }
    values.update(changes)
    return OwnerTenantAuthorityV3Revocation(**values)  # type: ignore[arg-type]


def test_v3_root_seals_exact_evidence_v5_and_is_read_only() -> None:
    """Seal the complete V5 assignment/policy graph with independent V3 hashes."""

    authority = _authority()
    validate_owner_tenant_authority_v3_root(authority)

    assert authority.owner == OWNER
    assert authority.artifact_type == ARTIFACT_TYPE
    assert authority.schema == SCHEMA
    assert authority.permission == PERMISSION == "evidence_read"
    assert authority.status == STATUS == "active"
    assert type(authority.assignment) is AccountOwnerAssignmentEvidenceV5
    assert authority.activation_available is False
    assert authority.must_not_execute is MUST_NOT_EXECUTE is True
    assert authority.assignment_evidence_id == authority.assignment.evidence_id
    assert authority.assignment_evidence_version == authority.assignment.evidence_version
    assert authority.assignment_evidence_content_hash == authority.assignment.content_hash
    assert authority.account_namespace == authority.policy.account_namespace
    assert authority.account_id == authority.policy.account_id
    assert authority.actor_id == authority.assignment.claimant.actor_id
    assert authority.actor_user_id == authority.assignment.claimant.user_id
    assert authority.is_root is True
    assert authority.is_current_at(authority.recorded_at) is True
    assert authority.is_current_at(authority.valid_until) is False
    assert authority.is_knowable_at(authority.recorded_at) is True
    assert authority.is_knowable_at(authority.recorded_at - timedelta(microseconds=1)) is False
    payload = authority.to_payload()
    assert payload["assignment"] == authority.assignment.to_payload()
    assert payload["policy"] == authority.policy.to_payload()
    assert payload["must_not_execute"] is True
    assert payload["supersedes_content_hash"] is None
    assert len(authority.identity_hash) == len(authority.content_hash) == 64
    assert not hasattr(authority, "__dict__")
    assert AUTHORITY_V3_IDENTITY_HASH_DOMAIN != "account.owner-tenant-authority.v2/identity"
    assert AUTHORITY_V3_CONTENT_HASH_DOMAIN != "account.owner-tenant-authority.v2/content"

    with pytest.raises(FrozenInstanceError):
        authority.authority_version = "v3.2"  # type: ignore[misc]


def test_v3_rejects_v4_or_untyped_assignment_substitution() -> None:
    """Keep the V3 authority boundary exact and closed to V4 or arbitrary values."""

    authority = _authority()
    with pytest.raises(TypeError, match="exact AccountOwnerAssignmentEvidenceV5"):
        replace(authority, assignment=cast(AccountOwnerAssignmentEvidenceV5, object()))
    with pytest.raises(TypeError, match="exact AccountOwnerAssignmentEvidenceV5"):
        replace(authority, assignment=cast(AccountOwnerAssignmentEvidenceV5, _v4_placeholder()))
    with pytest.raises(TypeError, match="exact SingleOwnerAuthorityPolicyV1"):
        replace(authority, policy=cast(object, object()))
    with pytest.raises(TypeError, match="exact AccountOwnerAssignmentActor"):
        replace(authority, approved_by=cast(object, object()))
    with pytest.raises(TypeError, match="identity_hash"):
        replace(authority, identity_hash=cast(str, object()))
    with pytest.raises(ValueError, match="content_hash"):
        replace(authority, content_hash="0" * 64)
    with pytest.raises(ValueError, match="fixed"):
        replace(authority, owner="other")


def _v4_placeholder() -> AccountOwnerAssignmentEvidenceV4:
    """Return a type-only V4 placeholder without constructing a valid graph."""

    return cast(AccountOwnerAssignmentEvidenceV4, object())


def test_v3_successor_preserves_scope_and_seals_the_exact_predecessor() -> None:
    """Allow one active same-owner successor with exact predecessor binding."""

    previous = _authority(
        valid_until=datetime(2026, 8, 15, 14, 50, tzinfo=UTC),
    )
    successor = _successor(previous)
    validate_owner_tenant_authority_v3_successor(previous, successor)

    assert successor.is_root is False
    assert successor.supersedes_content_hash == previous.content_hash
    assert successor.assignment is previous.assignment
    assert successor.policy is previous.policy
    assert successor.identity_hash != previous.identity_hash
    assert successor.content_hash != previous.content_hash

    with pytest.raises(ValueError, match="exact predecessor"):
        validate_owner_tenant_authority_v3_successor(
            previous,
            _successor(previous, supersedes_content_hash="f" * 64),
        )
    with pytest.raises(ValueError, match="version must advance"):
        validate_owner_tenant_authority_v3_successor(
            previous,
            _successor(previous, authority_version=previous.authority_version),
        )
    with pytest.raises(ValueError, match="scope"):
        validate_owner_tenant_authority_v3_successor(
            previous,
            _successor(previous, authority_id="other-authority"),
        )


def test_v3_successor_requires_a_current_predecessor_and_no_clock_rollback() -> None:
    """Reject successor creation after expiry or before the predecessor clocks."""

    previous = _authority(
        valid_until=datetime(2026, 8, 15, 14, 45, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="current active authority"):
        validate_owner_tenant_authority_v3_successor(
            previous,
            _successor(
                previous,
                approved_at=previous.approved_at,
                recorded_at=previous.valid_until + timedelta(minutes=1),
                valid_until=previous.valid_until + timedelta(minutes=2),
            ),
        )
    with pytest.raises(ValueError, match="approval clock"):
        validate_owner_tenant_authority_v3_successor(
            previous,
            _successor(previous, approved_at=previous.approved_at - timedelta(seconds=1)),
        )
    with pytest.raises(ValueError, match="recording clock must advance"):
        validate_owner_tenant_authority_v3_successor(
            previous,
            _successor(previous, recorded_at=previous.recorded_at),
        )


def test_v3_root_rejects_invalid_clocks_and_expiry() -> None:
    """Require an ordered aware interval and keep expiry terminal."""

    authority = _authority()
    with pytest.raises(ValueError, match="clock sequence"):
        _authority(recorded_at=authority.approved_at - timedelta(microseconds=1))
    with pytest.raises(ValueError, match="timezone-aware"):
        authority.is_current_at(datetime(2026, 8, 10, 12))
    with pytest.raises(ValueError, match="sealed policy"):
        _authority(valid_until=authority.policy.valid_until + timedelta(microseconds=1))
    with pytest.raises(ValueError, match="current assignment"):
        _authority(
            approved_at=authority.assignment.valid_until,
            recorded_at=authority.assignment.valid_until + timedelta(microseconds=1),
        )


def test_v3_revocation_binds_exact_decision_policy_and_same_owner() -> None:
    """Bind a human staff same-owner revoker without mutating the root."""

    authority = _authority()
    revocation = _revocation(
        authority,
        revoked_at=authority.recorded_at,
        recorded_at=authority.recorded_at,
    )
    validate_owner_tenant_authority_v3_revocation(authority, revocation)

    assert revocation.artifact_type == REVOCATION_ARTIFACT_TYPE
    assert revocation.schema == REVOCATION_SCHEMA
    assert revocation.authority_content_hash == authority.content_hash
    assert revocation.policy_content_hash == authority.policy.content_hash
    assert revocation.activation_available is False
    assert revocation.must_not_execute is True
    assert revocation.is_effective_at(revocation.recorded_at) is True
    assert revocation.is_knowable_at(revocation.recorded_at - timedelta(microseconds=1)) is False
    assert len(revocation.identity_hash) == len(revocation.content_hash) == 64
    assert (
        REVOCATION_V3_IDENTITY_HASH_DOMAIN
        != "account.owner-tenant-authority.v2-revocation/identity"
    )
    assert (
        REVOCATION_V3_CONTENT_HASH_DOMAIN != "account.owner-tenant-authority.v2-revocation/content"
    )

    with pytest.raises(FrozenInstanceError):
        revocation.reason = "other"  # type: ignore[misc]

    with pytest.raises(ValueError, match="match.*owner"):
        validate_owner_tenant_authority_v3_revocation(
            authority,
            replace(
                revocation,
                revoked_by=AccountOwnerAssignmentActor(
                    "other-owner",
                    authority.actor_user_id,
                    REVOKER_ROLE,
                    kind="human",
                    is_staff=True,
                ),
                identity_hash="",
                content_hash="",
            ),
        )


def test_v3_revocation_can_follow_expiry_and_remains_terminal() -> None:
    """Allow a known post-expiry revocation without reactivating the root."""

    authority = _authority()
    revoked_at = authority.valid_until + timedelta(minutes=5)
    revocation = _revocation(authority, revoked_at=revoked_at, recorded_at=revoked_at)
    validate_owner_tenant_authority_v3_revocation(authority, revocation)

    assert authority.is_current_at(authority.valid_until - timedelta(microseconds=1)) is True
    assert authority.is_current_at(revoked_at) is False
    assert revocation.is_effective_at(revoked_at) is True
    with pytest.raises(ValueError, match="fixed"):
        replace(revocation, status="active")


def test_v3_revocation_rejects_invalid_role_type_hash_and_clock() -> None:
    """Keep the revocation value strict before it is bound to the root."""

    authority = _authority()
    with pytest.raises(ValueError, match="reason"):
        _revocation(authority, reason="")
    with pytest.raises(ValueError, match="revoker"):
        _revocation(
            authority,
            revoked_by=AccountOwnerAssignmentActor(
                authority.actor_id,
                authority.actor_user_id,
                "wrong-role",
                kind="human",
                is_staff=True,
            ),
        )
    with pytest.raises(TypeError, match="exact AccountOwnerAssignmentActor"):
        _revocation(authority, revoked_by=cast(object, object()))
    with pytest.raises(ValueError, match="clock sequence"):
        _revocation(
            authority,
            revoked_at=datetime(2026, 8, 10, 12, tzinfo=UTC),
            recorded_at=datetime(2026, 8, 9, 12, tzinfo=UTC),
        )

    bad = _revocation(authority, authority_content_hash="0" * 64)
    with pytest.raises(ValueError, match="exact decision"):
        validate_owner_tenant_authority_v3_revocation(authority, bad)


def test_v3_validators_reject_substituted_types() -> None:
    """Keep root, successor, and revocation validators exact-type and fail closed."""

    with pytest.raises(TypeError, match="exact OwnerTenantAuthorityV3"):
        validate_owner_tenant_authority_v3_root(cast(OwnerTenantAuthorityV3, object()))

    authority = _authority()
    successor = _successor(authority)
    revocation = _revocation(authority)
    with pytest.raises(TypeError, match="exact OwnerTenantAuthorityV3"):
        validate_owner_tenant_authority_v3_successor(
            cast(OwnerTenantAuthorityV3, object()), successor
        )
    with pytest.raises(TypeError, match="exact OwnerTenantAuthorityV3"):
        validate_owner_tenant_authority_v3_successor(
            authority, cast(OwnerTenantAuthorityV3, object())
        )
    with pytest.raises(TypeError, match="exact OwnerTenantAuthorityV3"):
        validate_owner_tenant_authority_v3_revocation(
            cast(OwnerTenantAuthorityV3, object()), revocation
        )
    with pytest.raises(TypeError, match="exact OwnerTenantAuthorityV3Revocation"):
        validate_owner_tenant_authority_v3_revocation(
            authority, cast(OwnerTenantAuthorityV3Revocation, object())
        )
