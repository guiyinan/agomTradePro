"""Unit contracts for the explicit long-lived owner authority v2 Domain."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.account_owner_assignment_evidence_v4 import (
    AccountOwnerAssignmentEvidenceV4,
)
from apps.account.domain.owner_tenant_authority_v1 import (
    OwnerTenantAuthorityV1,
    validate_owner_tenant_authority_v1_root,
)
from apps.account.domain.owner_tenant_authority_v2 import (
    APPROVER_ROLE,
    ARTIFACT_TYPE,
    MUST_NOT_EXECUTE,
    PERMISSION,
    REVOCATION_ARTIFACT_TYPE,
    REVOCATION_SCHEMA,
    REVOKER_ROLE,
    SCHEMA,
    OwnerTenantAuthorityV2,
    OwnerTenantAuthorityV2Revocation,
    validate_owner_tenant_authority_v2_revocation,
    validate_owner_tenant_authority_v2_root,
)
from tests.unit.account.test_account_owner_assignment_evidence_v4 import _evidence, _subject
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v4 import _receipt
from tests.unit.account.test_owner_tenant_authority_v1 import _authority as _legacy_authority


def _at(
    day: int,
    hour: int = 12,
    minute: int = 0,
    second: int = 0,
    microsecond: int = 0,
) -> datetime:
    """Return one aware UTC test clock."""

    return datetime(2026, 8, day, hour, minute, second, microsecond, tzinfo=UTC)


def _authority(
    assignment: AccountOwnerAssignmentEvidenceV4 | None = None,
    **changes: object,
) -> OwnerTenantAuthorityV2:
    """Build one valid v2 root from the complete V4 assignment fixture."""

    value = assignment or _evidence()
    claimant = value.claimant
    values: dict[str, object] = {
        "authority_id": "authority-v2-7",
        "authority_version": "v2.1",
        "assignment": value,
        "policy": value.policy,
        "approved_by": AccountOwnerAssignmentActor(
            claimant.actor_id,
            claimant.user_id,
            APPROVER_ROLE,
            kind=claimant.kind,
            is_staff=True,
        ),
        "approved_at": _at(8, 18),
        "recorded_at": _at(8, 19),
        "valid_until": _at(14, 11),
    }
    values.update(changes)
    return OwnerTenantAuthorityV2(**values)  # type: ignore[arg-type]


def _revocation(
    authority: OwnerTenantAuthorityV2 | None = None,
    **changes: object,
) -> OwnerTenantAuthorityV2Revocation:
    """Build one valid revocation from the exact owner decision."""

    value = authority or _authority()
    values: dict[str, object] = {
        "authority_content_hash": value.content_hash,
        "policy_content_hash": value.policy.content_hash,
        "revoked_by": AccountOwnerAssignmentActor(
            value.actor_id,
            value.actor_user_id,
            REVOKER_ROLE,
            is_staff=True,
        ),
        "revoked_at": _at(14, 12),
        "recorded_at": _at(14, 12),
        "reason": "owner-request",
    }
    values.update(changes)
    return OwnerTenantAuthorityV2Revocation(**values)  # type: ignore[arg-type]


def test_v2_root_derives_scope_and_is_an_inactive_read_decision() -> None:
    """Seal the complete assignment/policy graph with independent v2 hashes."""

    authority = _authority()
    validate_owner_tenant_authority_v2_root(authority)
    payload = authority.to_payload()

    assert authority.artifact_type == ARTIFACT_TYPE
    assert authority.schema == SCHEMA
    assert authority.permission == PERMISSION == "evidence_read"
    assert authority.must_not_execute is MUST_NOT_EXECUTE is True
    assert authority.activation_available is False
    assert authority.tenant_id == authority.policy.tenant_id
    assert authority.owner_id == authority.policy.owner_id
    assert authority.account_namespace == authority.policy.account_namespace
    assert authority.account_id == authority.policy.account_id
    assert authority.actor_id == authority.assignment.claimant.actor_id
    assert authority.actor_user_id == authority.assignment.claimant.user_id
    assert payload["assignment"] == authority.assignment.to_payload()
    assert payload["policy"] == authority.policy.to_payload()
    assert payload["tenant_id"] == authority.tenant_id
    assert payload["must_not_execute"] is True
    assert len(authority.identity_hash) == len(authority.content_hash) == 64
    assert not hasattr(authority, "__dict__")

    with pytest.raises(FrozenInstanceError):
        authority.authority_version = "v2.2"  # type: ignore[misc]


def test_v2_root_requires_assignment_current_at_approval_and_recording() -> None:
    """Reject an approval or record clock after the short-lived assignment ends."""

    assignment = _evidence()
    with pytest.raises(ValueError, match="current assignment"):
        _authority(
            assignment=assignment,
            approved_at=assignment.valid_until,
            recorded_at=assignment.valid_until + timedelta(microseconds=1),
        )

    with pytest.raises(ValueError, match="clock sequence"):
        _authority(recorded_at=_at(8, 17, 59))

    with pytest.raises(ValueError, match="clock sequence"):
        _authority(valid_until=_at(8, 19))


def test_v2_decision_may_outlive_assignment_but_never_its_policy() -> None:
    """Keep a durable decision valid five minutes after assignment expiry."""

    authority = _authority()
    after_assignment = authority.assignment.valid_until + timedelta(minutes=5)
    assert authority.is_current_at(after_assignment) is True
    assert authority.is_current_at(authority.valid_until) is False
    assert authority.is_knowable_at(authority.recorded_at) is True
    assert authority.is_knowable_at(authority.recorded_at - timedelta(microseconds=1)) is False

    with pytest.raises(ValueError, match="sealed policy"):
        _authority(valid_until=authority.policy.valid_until + timedelta(microseconds=1))

    with pytest.raises(ValueError, match="timezone-aware"):
        authority.is_current_at(datetime(2026, 8, 10, 12))

    short_receipt = _receipt(valid_until=_at(8, 22))
    short_subject = _subject(
        short_receipt,
        requested_at=_at(8, 15),
        valid_until=_at(8, 22),
    )
    short_assignment = replace(
        _evidence(
            short_subject,
            approved_at=_at(8, 16),
            recorded_at=_at(8, 17),
            approval_valid_until=_at(8, 22),
            valid_until=_at(8, 22),
        ),
        identity_hash="",
        content_hash="",
    )
    short_authority = _authority(
        assignment=short_assignment,
        approved_at=_at(8, 17, 30),
        recorded_at=_at(8, 18),
    )
    assert short_assignment.is_current_at(short_authority.recorded_at) is True
    assert (
        short_assignment.is_current_at(short_assignment.valid_until + timedelta(minutes=5)) is False
    )
    assert (
        short_authority.is_current_at(short_assignment.valid_until + timedelta(minutes=5)) is True
    )


def test_v2_root_rejects_cross_policy_or_nonmatching_owner_actor() -> None:
    """Require the exact Subject policy and the same real staff owner actor."""

    assignment = _evidence()
    other_policy = replace(
        assignment.policy,
        policy_version="2",
        identity_hash="",
        content_hash="",
    )
    with pytest.raises(ValueError, match="equal.*Subject policy"):
        _authority(assignment=assignment, policy=other_policy)

    with pytest.raises(ValueError, match="match.*owner actor"):
        _authority(
            approved_by=AccountOwnerAssignmentActor(
                "different-owner",
                assignment.claimant.user_id,
                APPROVER_ROLE,
                is_staff=True,
            )
        )

    with pytest.raises(ValueError, match="approver"):
        _authority(
            approved_by=AccountOwnerAssignmentActor(
                assignment.claimant.actor_id,
                assignment.claimant.user_id,
                "other-role",
                is_staff=True,
            )
        )


def test_v2_root_rejects_substituted_graph_types_hashes_and_fixed_semantics() -> None:
    """Reject non-domain parents, invalid seals, and attempts to change V2 state."""

    authority = _authority()
    with pytest.raises(TypeError, match="exact AccountOwnerAssignmentEvidenceV4"):
        replace(authority, assignment=cast(AccountOwnerAssignmentEvidenceV4, object()))
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


def test_v2_revocation_binds_exact_decision_policy_and_owner() -> None:
    """Bind a dedicated same-owner revoker without changing the root record."""

    authority = _authority()
    revocation = _revocation(authority, revoked_at=_at(9), recorded_at=_at(9))
    validate_owner_tenant_authority_v2_revocation(authority, revocation)

    assert revocation.artifact_type == REVOCATION_ARTIFACT_TYPE
    assert revocation.schema == REVOCATION_SCHEMA
    assert revocation.authority_content_hash == authority.content_hash
    assert revocation.policy_content_hash == authority.policy.content_hash
    assert revocation.revoked_by.role == REVOKER_ROLE
    assert revocation.activation_available is False
    assert revocation.must_not_execute is True
    assert revocation.to_payload()["must_not_execute"] is True
    assert revocation.is_effective_at(_at(9)) is True
    assert revocation.is_knowable_at(_at(9) - timedelta(microseconds=1)) is False
    assert len(revocation.identity_hash) == len(revocation.content_hash) == 64
    assert authority.is_current_at(_at(8, 23)) is True

    with pytest.raises(FrozenInstanceError):
        revocation.reason = "other"  # type: ignore[misc]


def test_v2_revocation_can_follow_expiry_without_retroactive_reactivation() -> None:
    """Allow a post-expiry event while preserving the root's historical interval."""

    authority = _authority()
    revoked_at = authority.valid_until + timedelta(minutes=5)
    revocation = _revocation(authority, revoked_at=revoked_at, recorded_at=revoked_at)
    validate_owner_tenant_authority_v2_revocation(authority, revocation)

    assert authority.is_current_at(authority.valid_until - timedelta(microseconds=1)) is True
    assert authority.is_current_at(revoked_at) is False
    assert revocation.is_effective_at(revoked_at) is True
    with pytest.raises(ValueError, match="fixed"):
        replace(revocation, status="active")


def test_v2_revocation_rejects_invalid_reason_role_type_and_clock() -> None:
    """Keep the revocation artifact itself strict before authority binding."""

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
                is_staff=True,
            ),
        )
    with pytest.raises(TypeError, match="exact AccountOwnerAssignmentActor"):
        _revocation(authority, revoked_by=cast(object, object()))
    with pytest.raises(ValueError, match="clock sequence"):
        _revocation(authority, revoked_at=_at(10), recorded_at=_at(9))


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"authority_content_hash": "0" * 64}, "authority content hash"),
        ({"policy_content_hash": "0" * 64}, "policy content hash"),
        (
            {
                "revoked_by": AccountOwnerAssignmentActor(
                    "other-owner",
                    42,
                    REVOKER_ROLE,
                    is_staff=True,
                )
            },
            "match.*owner",
        ),
        ({"revoked_at": _at(8, 18, 59), "recorded_at": _at(8, 19)}, "precede"),
    ],
)
def test_v2_revocation_rejects_hash_actor_or_clock_substitution(
    changes: dict[str, object], message: str
) -> None:
    """Reject any revocation that cannot be tied to the exact durable root."""

    authority = _authority()
    revocation = _revocation(authority, **changes)
    with pytest.raises(ValueError, match=message):
        validate_owner_tenant_authority_v2_revocation(authority, revocation)


def test_v1_authority_remains_unchanged_and_separate_from_v2() -> None:
    """Keep the historical V1 contract importable while V2 uses new semantics."""

    legacy = _legacy_authority()
    validate_owner_tenant_authority_v1_root(legacy)
    assert isinstance(legacy, OwnerTenantAuthorityV1)
    assert legacy.schema == "account.owner_tenant_authority.v1"
    assert legacy.permission == "evidence_read"
    assert legacy.content_hash != _authority().content_hash


def test_v2_validators_reject_substituted_types() -> None:
    """Keep root and revocation validators exact-type and fail closed."""

    with pytest.raises(TypeError, match="exact OwnerTenantAuthorityV2"):
        validate_owner_tenant_authority_v2_root(cast(OwnerTenantAuthorityV2, object()))

    authority = _authority()
    revocation = _revocation(authority)
    with pytest.raises(TypeError, match="exact OwnerTenantAuthorityV2"):
        validate_owner_tenant_authority_v2_revocation(
            cast(OwnerTenantAuthorityV2, object()), revocation
        )
    with pytest.raises(TypeError, match="exact OwnerTenantAuthorityV2Revocation"):
        validate_owner_tenant_authority_v2_revocation(
            authority, cast(OwnerTenantAuthorityV2Revocation, object())
        )
